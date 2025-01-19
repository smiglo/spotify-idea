import json
import os
import random
import requests
import string
import time
import webbrowser
import urllib.parse

from datetime import datetime, timedelta

config = {}
urls = {}
headers = {}

def j2s(j, justPrint=False):
    if justPrint:
        print(json.dumps(j, indent=2, ensure_ascii=False))
        return None
    return json.dumps(j, indent=2, ensure_ascii=False)

def expires_at(expires_in):
    expires_at = datetime.now() + timedelta(seconds=expires_in)
    return int(expires_at.timestamp())

def load(fname):
    if not os.path.exists(fname):
        return {}
    with open(fname, "r") as f:
        return json.load(f)

def save(data, fname):
    with open(fname, "w") as f:
        json.dump(data, f, indent=2)

def load_config():
    config = load("config.json")
    config["runtime"] = load("config-runtime.json")
    if not "client" in config["runtime"]:
        config["runtime"]["client"] = {
            "id": os.environ[config["client"]["id_env"]],
            "secret": os.environ[config["client"]["secret_env"]]
        }
    return config

def save_config(config):
    c = config.copy()
    c["runtime"] = {}
    save(c, "config.json")
    save(config["runtime"], "config-runtime.json")

def mk_req(url, method="GET", payload=None, loop=False):
    global headers
    ret = []
    i = 0
    print_progress = False
    while url:
        i += 1
        if loop and print_progress:
            print(f"getting: {i}")
        response = requests.request(method, url, headers=headers, params=payload)
        if response.status_code != 200:
            print(f"Error at {i}: {response.status_code} :: {url}")
            j2s(response.json(), True)
            if payload: print(payload)
            if loop:
                break
            return None
        r_json = response.json()
        if not loop:
            return r_json
        ret += r_json["items"]
        url = r_json["next"]
    return ret

def get_app_token():
    access_delta = 1 * 60
    access_token = None
    global config

    if "app_access" in config["runtime"]:
        access = config["runtime"]["app_access"]
        if datetime.now().timestamp() < access["expires_at"] - access_delta:
            access_token = access["access_token"]
        else:
            print("revoking")

    if not access_token:
        print("from spotify")
        response = requests.post(urls["token"],
            headers={
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data={
                "grant_type"   : "client_credentials",
                "client_id"    : config["runtime"]["client"]["id"],
                "client_secret": config["runtime"]["client"]["secret"]
        })

        if response.status_code != 200:
            print(f"fail in get_app_token: {j2s(response.json())}")
            return None

        access = response.json()
        access["expires_at"] = expires_at(access["expires_in"])
        config["runtime"]["app_access"] = access
        save_config(config)

    return config["runtime"]["app_access"]["access_token"]

def authorize_user():
    global config

    state = "".join(random.choices(string.ascii_letters + string.digits, k=16))
    config["runtime"]["state"] = state
    save_config(state)
    auth_url = urls["auth"] + "?" + urllib.parse.urlencode({
        "client_id": config["runtime"]["client"]["id"],
        "response_type": "code",
        "redirect_uri": urls["cback"],
        "state": state,
        "scope": " ".join(config["scope"]),
        "show_dialog": config["show_dialog"]
    })
    webbrowser.open(auth_url, new=0, autoraise=True)

    delta = 3 * 60
    sleepS = 5
    untilTs =  datetime.now().timestamp() + delta
    user_auth_code = None
    while datetime.now().timestamp() < untilTs:
        time.sleep(sleepS)
        c = load_config()
        if "user_auth_code" in c["runtime"]:
            user_auth_code = c["runtime"]["user_auth_code"]
            break

    del config["runtime"]["state"]
    save_config(config)

    if not user_auth_code:
        return None

    response = requests.post(
        urls["token"],
        headers={
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        data={
            "grant_type": "authorization_code",
            "code": user_auth_code,
            "redirect_uri": urls["cback"],
            "client_id": config["runtime"]["client"]["id"],
            "client_secret": config["runtime"]["client"]["secret"]
    })

    if response.status_code != 200:
        print(f"fail in authorize_user: {j2s(response.json())}")
        return None

    user_auth = response.json()
    user_auth["expires_at"] = expires_at(user_auth["expires_in"])
    config["runtime"]["user_auth"] = user_auth
    save_config(config)

def refresh_user_token():
    global config

    if not "refresh_token" in config["runtime"]["user_auth"]:
        authorize_user()
        return

    refresh_token = config["runtime"]["user_auth"]["refresh_token"]
    response = requests.post(
        urls["token"],
        headers={
            "Content-Type": "application/x-www-form-urlencoded"
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": config["runtime"]["client"]["id"],
            "client_secret": config["runtime"]["client"]["secret"]
    })

    if response.status_code != 200:
        print(f"fail in refresh_user_token {j2s(response.json())}")
        del config["runtime"]["user_auth"]
        save_config(config)
        return

    user_auth = response.json()
    if not refresh_token in user_auth:
        user_auth["refresh_token"] = refresh_token
    user_auth["expires_at"] = expires_at(user_auth["expires_in"])
    config["runtime"]["user_auth"] = user_auth
    save_config(config)

def get_user_token():
    if not "user_auth" in config["runtime"]:
        authorize_user()
    else:
        refresh_user_token()

    if not "user_auth" in config["runtime"]:
        return None

    if not "access_token" in config["runtime"]["user_auth"]:
        return None

    return config["runtime"]["user_auth"]["access_token"]

if __name__ == "__main__":
    config = load_config()
    urls = {
        "token":  "https://accounts.spotify.com/api/token",
        "auth" :  "https://accounts.spotify.com/authorize",
        "api"  :  "https://api.spotify.com/v1",
        "cback": f"http://localhost:{config['callback_port']}/callback",
    }

    access_token = get_app_token()
    print(access_token)

    if not access_token:
        print("ERR: no access token")
        exit(1)

    user_token = get_user_token()
    if not user_token:
        print("ERR: no user token")
        exit(1)

    headers = {
        "Authorization": f"Bearer {user_token}",
    }

    user = load("user.json")
    if not user:
        print("getting user")
        user = mk_req(f"{urls['api']}/me")
        save(user, "user.json")

    user_ref = user["href"]

    favs = load("favs.json")
    if not favs:
        print("getting favs")
        favs = mk_req(f"{urls['api']}/me/tracks", payload={"limit": 50}, loop=True)
        for i in favs:
            del i["track"]["available_markets"]
            del i["track"]["album"]["available_markets"]
        save(favs, "favs.json")

    playlists = load("playlists.json")
    if not playlists:
        print("getting playlists")
        playlists = mk_req(f"{user_ref}/playlists", loop=True)
        save(playlists, "playlists.json")

    car_playlist = None
    car_items = None
    for p in playlists:
        p_id = p["id"]
        items = load(f"playlist-{p_id}.json")
        if not items and not os.path.exists(f"playlist-{p_id}.json"):
            print(f"getting playlist: {p_id} {p['name']}")
            items = mk_req(p["tracks"]["href"], payload={"limit": 50}, loop=True)
            j2s(items, True)
            for i in items:
                del i["track"]["available_markets"]
                del i["track"]["album"]["available_markets"]
            save(items, f"playlist-{p_id}.json")
        if p["name"] == "Car":
            car_playlist = p_id
            car_items = items.copy()

    print(car_playlist)
    # album["id"] = {
    #   "name" : "",
    #   "total_tracks": 0,
    #   "tracks": [ "IDs" ]
    # }
    # artis["id"] = {
    #   "name" : "",
    #   "albums": [ "IDs" ],
    #   "tracks": [ "IDs" ]
    # }
    # track["id"] = {
    #   "name": "",
    #   "popularity": 0,
    #   "artists": [ "IDs" ],
    #   "albums": "IDs",
    #   "track_number": 0,
    #   "duration_ms": 0,
    #   "external_ids-isrc": ""
    # }
    album = {}
    artist = {}
    track = {}
    for i in car_items:
        i = i["track"]
        # j2s(i, True)
        tid = i["id"]
        if not tid:
            continue
        if not tid in track:
            track[tid] = {
                "name": i["name"],
                "id": tid,
                "artists": [a["id"] for a in i["artists"]],
                "album": i["album"]["id"],
                "popularity": i["popularity"],
                "track_number": i["track_number"],
                "duration_ms": i["duration_ms"],
                # "external_ids-isrc": i["external_ids"]["isrc"] or None,
            }
        else:
            print(f"track: already added: {tid}")

        alid = i["album"]["id"]
        if not alid in album:
            album[alid] = {
                "name": i["album"]["name"],
                "id": alid,
                # "total_tracks": i["album"]["total_tracks"],
                "tracks": [],
            }
        if not tid in album[alid]["tracks"]:
            album[alid]["tracks"].append(tid)
        else:
            print(f"track to album: already added: {tid} to {alid}")

        for ar in i["artists"]:
            arid = ar["id"]
            if not arid in artist:
                artist[arid] = {
                    "name": ar["name"],
                    "id": arid,
                    "albums": [],
                    "tracks": [],
                }
            if not tid in artist[arid]["tracks"]:
                artist[arid]["tracks"].append(tid)
            else:
                print(f"track to artist: already added: {tid} to {arid}")
            if not alid in artist[arid]["albums"]:
                artist[arid]["albums"].append(alid)

    print("--- artists # {{{")
    j2s(artist, True)
    print("# }}}")
    print("--- albums # {{{")
    j2s(album, True)
    print("# }}}")
    print("--- tracks # {{{")
    j2s(track, True)
    print("# }}}")
    print("--- sorted # {{{")
    sorted_tracks = sorted(list(track.values()), key=lambda x: x["popularity"])
    j2s(sorted_tracks, True)
    print("# }}}")


