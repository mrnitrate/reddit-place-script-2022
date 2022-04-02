import os
import os.path
import math
from datetime import datetime, timedelta

import requests
import json
import time
import threading
import logging
import colorama
import argparse
from io import BytesIO
from websocket import create_connection
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
from PIL import ImageColor
from PIL import Image
import random


from mappings import color_map, name_map

# Option remains for legacy usage
# equal to running
# python main.py --verbose
verbose_mode = False


# Get a more verbose color indicator from a pixel color ID
def color_id_to_name(color_id):
    if color_id in name_map.keys():
        return f"{name_map[color_id]} ({str(color_id)})"
    return f"Invalid Color ({str(color_id)})"


# method to draw a pixel at an x, y coordinate in r/place with a specific color
def set_pixel_and_check_ratelimit(
    access_token_in, x, y, color_index_in=18, canvas_index=1
):
    logging.info(
        f"Attempting to place {color_id_to_name(color_index_in)} pixel at {x}, {y}"
    )

    url = "https://gql-realtime-2.reddit.com/query"

    payload = json.dumps(
        {
            "operationName": "setPixel",
            "variables": {
                "input": {
                    "actionName": "r/replace:set_pixel",
                    "PixelMessageData": {
                        "coordinate": {"x": x % 1000, "y": y},
                        "colorIndex": color_index_in,
                        "canvasIndex": canvas_index,
                    },
                }
            },
            "query": (
                "mutation setPixel($input: ActInput!) {\n  act(input: $input) {\n   "
                " data {\n      ... on BasicMessage {\n        id\n        data {\n    "
                "      ... on GetUserCooldownResponseMessageData {\n           "
                " nextAvailablePixelTimestamp\n            __typename\n          }\n   "
                "       ... on SetPixelResponseMessageData {\n            timestamp\n  "
                "          __typename\n          }\n          __typename\n        }\n  "
                "      __typename\n      }\n      __typename\n    }\n    __typename\n "
                " }\n}\n"
            ),
        }
    )
    headers = {
        "origin": "https://hot-potato.reddit.com",
        "referer": "https://hot-potato.reddit.com/",
        "apollographql-client-name": "mona-lisa",
        "Authorization": f"Bearer {access_token_in}",
        "Content-Type": "application/json",
    }

    response = requests.request("POST", url, headers=headers, data=payload)
    logging.debug(f"Received response: {response.text}")
    # There are 2 different JSON keys for responses to get the next timestamp.
    # If we don't get data, it means we've been rate limited.
    # If we do, a pixel has been successfully placed.
    if response.json()["data"] is None:
        waitTime = response.json()["errors"][0]["extensions"]["nextAvailablePixelTs"]

        logging.info(
            f"{colorama.Fore.RED}Failed placing pixel: rate limited"
            f" {colorama.Style.RESET_ALL}"
        )
    else:
        waitTime = response.json()["data"]["act"]["data"][0]["data"][
            "nextAvailablePixelTimestamp"
        ]
        logging.info(
            f"{colorama.Fore.GREEN}Succeeded placing pixel {colorama.Style.RESET_ALL}"
        )

    return datetime.fromtimestamp(waitTime / 1000)


def get_board(bearer):
    ws = create_connection("wss://gql-realtime-2.reddit.com/query")
    ws.send(
        json.dumps(
            {
                "type": "connection_init",
                "payload": {"Authorization": "Bearer " + bearer},
            }
        )
    )
    ws.recv()
    ws.send(
        json.dumps(
            {
                "id": "1",
                "type": "start",
                "payload": {
                    "variables": {
                        "input": {
                            "channel": {"teamOwner": "AFD2022", "category": "CONFIG"}
                        }
                    },
                    "extensions": {},
                    "operationName": "configuration",
                    "query": (
                        "subscription configuration($input: SubscribeInput!) {\n "
                        " subscribe(input: $input) {\n    id\n    ... on BasicMessage"
                        " {\n      data {\n        __typename\n        ... on"
                        " ConfigurationMessageData {\n          colorPalette {\n       "
                        "     colors {\n              hex\n              index\n       "
                        "       __typename\n            }\n            __typename\n    "
                        "      }\n          canvasConfigurations {\n            index\n"
                        "            dx\n            dy\n            __typename\n      "
                        "    }\n          canvasWidth\n          canvasHeight\n        "
                        "  __typename\n        }\n      }\n      __typename\n    }\n   "
                        " __typename\n  }\n}\n"
                    ),
                },
            }
        )
    )
    ws.recv()
    image_sizex = 2
    image_sizey = 1
    imgs = []
    already_added = []
    for i in range(0, image_sizex * image_sizey):
        ws.send(
            json.dumps(
                {
                    "id": str(2 + i),
                    "type": "start",
                    "payload": {
                        "variables": {
                            "input": {
                                "channel": {
                                    "teamOwner": "AFD2022",
                                    "category": "CANVAS",
                                    "tag": str(i),
                                }
                            }
                        },
                        "extensions": {},
                        "operationName": "replace",
                        "query": (
                            "subscription replace($input: SubscribeInput!) {\n "
                            " subscribe(input: $input) {\n    id\n    ... on"
                            " BasicMessage {\n      data {\n        __typename\n       "
                            " ... on FullFrameMessageData {\n          __typename\n    "
                            "      name\n          timestamp\n        }\n        ... on"
                            " DiffFrameMessageData {\n          __typename\n         "
                            " name\n          currentTimestamp\n         "
                            " previousTimestamp\n        }\n      }\n      __typename\n"
                            "    }\n    __typename\n  }\n}\n"
                        ),
                    },
                }
            )
        )
        while True:
            temp = json.loads(ws.recv())
            if temp["type"] == "data":
                msg = temp["payload"]["data"]["subscribe"]
                if msg["data"]["__typename"] == "FullFrameMessageData":
                    if not temp["id"] in already_added:
                        imgs.append(
                            Image.open(
                                BytesIO(
                                    requests.get(
                                        msg["data"]["name"], stream=True
                                    ).content
                                )
                            )
                        )
                        already_added.append(temp["id"])
                    break
        ws.send(json.dumps({"id": str(2 + i), "type": "stop"}))

    ws.close()
    new_im = Image.new("RGB", (1000 * 2, 1000))
    x_offset = 0
    for img in imgs:
        new_im.paste(img, (x_offset, 0))
        x_offset += img.size[0]

    return new_im


def get_unset_pixel(boardimg):
    pixel_x_start = int(os.getenv("ENV_DRAW_X_START"))
    pixel_y_start = int(os.getenv("ENV_DRAW_Y_START"))
    pix2 = boardimg.convert("RGB").load()
    x_cord = pixel_x_start
    y_cord = pixel_y_start
    while True:
        while y_cord > 900:
            while x_cord > 1900:
                if pix2[x_cord, y_cord] != (36, 80, 164):
                    return x_cord, y_cord
                x_cord -= 1
            x_cord = 1998
            y_cord -= 1
        y_cord = 998


# task to draw the input image
def task(credentials_index):
    # whether image should keep drawing itself

    while True:
        # string for time until next pixel is drawn
        update_str = ""

        # reference to globally shared variables such as auth token and image
        global access_tokens
        global access_token_expires_at_timestamp

        # boolean to place a pixel the moment the script is first run
        # global first_run
        global first_run_counter

        # refresh auth tokens and / or draw a pixel
        first_run_counter = True
        last_time_placed_pixel = datetime.now()
        while True:
            # reduce CPU usage
            time.sleep(1)

            # get the current time
            current_timestamp = datetime.now()

            # log next time until drawing
            time_until_next_draw = math.ceil(
                (last_time_placed_pixel - current_timestamp).total_seconds()
            )
            if time_until_next_draw % 10 == 0:
                new_update_str = (
                    f"{time_until_next_draw} seconds until next pixel is drawn"
                )
                logging.info(f"Thread #{credentials_index} :: {new_update_str}")

            if time_until_next_draw > 10000:
                logging.info(f"Thread #{credentials_index} :: CANCELLED")
                exit(1)

            # refresh access token if necessary
            if (
                access_tokens[credentials_index] is None
                or int(current_timestamp.timestamp())
                >= access_token_expires_at_timestamp[credentials_index]
            ):
                logging.info(f"Thread #{credentials_index} :: Refreshing access token")

                # developer's reddit username and password
                try:
                    username = json.loads(os.getenv("ENV_PLACE_USERNAME"))[
                        credentials_index
                    ]
                    password = json.loads(os.getenv("ENV_PLACE_PASSWORD"))[
                        credentials_index
                    ]

                    # note: use https://www.reddit.com/prefs/apps
                    app_client_id = os.getenv("ENV_PLACE_APP_CLIENT_ID")
                    secret_key = os.getenv("ENV_PLACE_SECRET_KEY")
                except IndexError:
                    print(
                        "Array length error: are you sure your credentials have an"
                        " equal amount of items?\n",
                        "Example for 2 accounts:\n",
                        'ENV_PLACE_USERNAME=\'["Username1", "Username2]\'\n',
                        'ENV_PLACE_PASSWORD=\'["Password", "Password"]\'\n',
                        'ENV_PLACE_APP_CLIENT_ID=\'["NBVSIBOPVAINCVIAVBOVV",'
                        ' "VNOPSNSJVQNVNJVSNVDV"]\'\n',
                        'ENV_PLACE_SECRET_KEY=\'["INSVDSINDJV_SVTNNJSNVNJV",'
                        ' "ANIJCINLLPJCSCOJNCA_ASDV"]\'\n',
                        "Note: There can be duplicate entries, but every array must"
                        " have the same amount of items.",
                    )
                    exit(1)

                data = {
                    "grant_type": "password",
                    "username": username,
                    "password": password,
                }

                r = requests.post(
                    "https://ssl.reddit.com/api/v1/access_token",
                    data=data,
                    auth=HTTPBasicAuth(app_client_id, secret_key),
                    headers={"User-agent": f"placebbot{random.randint(1, 100000)}"},
                )

                logging.debug(
                    f"Thread #{credentials_index} :: Received response: {r.text}"
                )
                response_data = r.json()
                access_tokens[credentials_index] = response_data["access_token"]
                # access_token_type = response_data["token_type"]  # this is just "bearer"
                access_token_expires_in_seconds = response_data[
                    "expires_in"
                ]  # this is usually "3600"
                # access_token_scope = response_data["scope"]  # this is usually "*"

                # ts stores the time in seconds
                access_token_expires_at_timestamp[credentials_index] = int(
                    (
                        current_timestamp
                        + timedelta(seconds=access_token_expires_in_seconds)
                    ).timestamp()
                )
                logging.info(
                    f"Thread #{credentials_index} :: Received new access token:"
                    f" {access_tokens[credentials_index][:5]}************"
                )

            # draw pixel onto screen
            if access_tokens[credentials_index] is not None and (
                current_timestamp >= last_time_placed_pixel or first_run_counter
            ):
                first_run_counter = False
                # get next non blue pixel to replace
                current_r, current_c = get_unset_pixel(
                    get_board(access_tokens[credentials_index]),
                )

                # draw the pixel onto r/place
                last_time_placed_pixel = set_pixel_and_check_ratelimit(
                    access_tokens[credentials_index],
                    current_r,
                    current_c,
                    12,
                )


# # # # #  MAIN # # # # # #

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    colorama.init()
    parser.add_argument(
        "-v",
        "--verbose",
        help="Be verbose",
        action="store_const",
        dest="loglevel",
        const=logging.DEBUG,
        default=logging.INFO,
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=(logging.DEBUG if verbose_mode else args.loglevel),
        format="[%(asctime)s] :: [%(levelname)s] - %(message)s",
        datefmt="%d-%b-%y %H:%M:%S",
    )
    logging.info("place-script started")
    if os.path.exists("./.env"):
        # load env variables
        load_dotenv()
    else:
        envfile = open(".env", "w")
        envfile.write(
            """ENV_PLACE_USERNAME='["developer_username"]'
ENV_PLACE_PASSWORD='["developer_password"]'
ENV_PLACE_APP_CLIENT_ID='["app_client_id"]'
ENV_PLACE_SECRET_KEY='["app_secret_key"]'
ENV_DRAW_X_START="x_position_start_integer"
ENV_DRAW_Y_START="y_position_start_integer"
ENV_R_START='["0"]'
ENV_C_START='["0"]\'"""
        )
        print(
            "No .env file found. A template has been created for you.",
            "Read the README and configure it properly.",
            "Right now, it's full of example data, so you ABSOLUTELY MUST edit it.",
        )
        logging.fatal("No .env file found")
        exit()

    # auth variables
    access_tokens = []
    access_token_expires_at_timestamp = []

    # get number of concurrent threads to start
    num_credentials = len(json.loads(os.getenv("ENV_PLACE_USERNAME")))

    # define delay between starting new threads
    if os.getenv("ENV_THREAD_DELAY") is not None:
        delay_between_launches_seconds = int(os.getenv("ENV_THREAD_DELAY"))
    else:
        delay_between_launches_seconds = 3

    # launch a thread for each account specified in .env
    for i in range(num_credentials):
        # run the image drawing task
        access_tokens.append(None)
        access_token_expires_at_timestamp.append(math.floor(time.time()))
        thread1 = threading.Thread(target=task, args=[i])
        thread1.start()
        time.sleep(delay_between_launches_seconds)
