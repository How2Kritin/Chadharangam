from flask import Flask, render_template, redirect, request, session, flash, url_for  # Import Flask and render_template classes from the flask module.
from flask_cors import CORS
from flask_socketio import SocketIO, send, join_room, leave_room, emit
from flask_bcrypt import Bcrypt  # Shall use bcrypt (Blowfish cypher) to hash passwords (one-way).
import sqlite3
import os  # to create a directory for the databases, if a directory doesn't exist already.
import random

path = "Databases"
if not os.path.exists(path):
    os.makedirs(path)

# Create the databases
database = sqlite3.connect('Databases/users.db')
database.execute(
    "CREATE TABLE IF NOT EXISTS USERS (username TEXT PRIMARY KEY, passwordHash TEXT, wins INT DEFAULT 0, losses INT DEFAULT 0, draws INT DEFAULT 0)")

# Create the flask server and initialise the session
app = Flask(__name__)
app.config["SESSION_PERMANENT"] = True
app.config["SESSION_TYPE"] = "filesystem"
app.config["SECRET_KEY"] = "somerandosecretkeylol1729!!"
socketio = SocketIO(app)
bcrypt = Bcrypt(app)

CORS(app)

# Miscellaneous global variables
rooms = dict()
uppercaseLetters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def generate_random_string(length):
    while True:
        code = ""
        for _ in range(length):
            code += random.choice(uppercaseLetters)
        if code not in rooms:
            break
    return code


# All the routes and their associated functions:
@app.route("/", methods=["POST", "GET"])
def auth():
    listOfQuotes = ["Chess players know how to mate!", "Google En Passant", "pawnhub.com", "Chess speaks for itself!",
                    "Always defend your bishop with your other bishop"]
    quote = random.choice(listOfQuotes)
    return render_template("auth.html", quote=quote)


@app.route("/userdata", methods=['POST'])
def handleUser():
    username = request.form.get('username')
    password = request.form.get('password')
    passwordHash = bcrypt.generate_password_hash(password).decode('UTF-8')
    room_code = request.form.get('room_code')

    if room_code:
        print(f"Username is {username}, entered password's hash is {passwordHash}, room code entered is {room_code}.")
        # Check if the entered room code is valid.
        if room_code not in rooms:
            flash(
                "A room with this code doesn't exist. Please enter a valid room code, or don't enter a room code at all to create a new room.")
            return redirect(url_for("auth"))

    else:
        print(
            f"Username is {username}, entered password's hash is {passwordHash}. Generating a room code. Will use the room code if the username and password are valid.")
        room_code = generate_random_string(4)
        while room_code in rooms:
            room_code = generate_random_string(4)
        rooms[room_code] = {"members": 0, "allMoves": [], "player1": {"username": "", "clientID": ""},
                            "player2": {"username": "", "clientID": ""}, "inProgress": False, "whoWon": "", "messages": []}

    # First, check if this user exists in the database.
    with sqlite3.connect('Databases/users.db') as database:
        cursor = database.cursor()
        query = f'SELECT username, passwordHash FROM USERS WHERE username="{username}"'
        cursor.execute(query)
        data = cursor.fetchall()  # List of tuples

        if len(data) != 0:  # Check if user already exists in the database
            if not bcrypt.check_password_hash(data[0][1], password):
                flash(
                    "This username already exists in the database, but the entered password is incorrect. You can either enter the correct password to log in, or use a different username to create an account.")
                return redirect(url_for("auth"))
            else:
                print("Successfully logged in!")
                session['username'], session['room_code'] = username, room_code
                return redirect(url_for("waitForPlayer"))
        else:
            print("New user, creating an account.")
            cursor.execute("INSERT INTO USERS (username, passwordHash) VALUES (?, ?)", (username, passwordHash))
            database.commit()
            print("Successfully added this user to the database!")
            session['username'], session['room_code'] = username, room_code
            return redirect(url_for("waitForPlayer"))


@app.route("/game", methods=['GET', 'POST'])
def waitForPlayer():
    if request.method == "POST":
        logout()

    username, room_code = session.get('username'), session.get('room_code')
    if room_code is None or username is None or room_code not in rooms:
        return redirect(url_for("auth"))
    elif rooms[room_code]["members"] >= 2:
        flash("Sorry, this room already has 2 players! Please join a different room, or create a new room.")
        return redirect(url_for("auth"))
    elif rooms[room_code]["inProgress"] and rooms[room_code]["player1"]["username"] != username and rooms[room_code]["player2"]["username"] != username:
        flash("Sorry, this room has a game currently in progress. Please join a different room, or create a new room.")
        return redirect(url_for("auth"))

    return render_template("chessroom.html", username=username, room_code=room_code, messages=rooms[room_code]["messages"])


def logout():
    session.clear()
    return redirect(url_for("auth"))


@app.route("/script_js")
def script_js():
    return render_template("js/script.js")


@socketio.on("connect")
def connect():
    username, room_code = session.get('username'), session.get('room_code')
    if room_code is None or username is None:
        return
    elif room_code not in rooms:  # If the user is in a room that doesn't exist as a valid room, then kick them out of that room.
        leave_room(room_code)
        return

    resumeGame = False
    rooms[room_code]["members"] += 1
    if not rooms[room_code]["inProgress"]:  # If the game hasn't started, do this.
        if rooms[room_code]["members"] == 1:
            rooms[room_code]["player1"]["username"] = username
            rooms[room_code]["player1"]["clientID"] = request.sid
        else:
            rooms[room_code]["player2"]["username"] = username
            rooms[room_code]["player2"]["clientID"] = request.sid

    else:  # Update their SID, and automatically resume their ongoing game.
        if rooms[room_code]["player1"]["username"] == username:
            rooms[room_code]["player1"]["clientID"] = request.sid
            color, player, resumeGame = ("White", rooms[room_code]["player1"], True)
        elif rooms[room_code]["player2"]["username"] == username:
            rooms[room_code]["player2"]["clientID"] = request.sid
            color, player, resumeGame = ("Black", rooms[room_code]["player2"], True)
        else:  # A random player has joined. Reject their connect request.
            print(f"Player with {username} tried to join the room {room_code} which already has a running game. They weren't in the room when the game started. Kicking them out.")
            rooms[room_code]["members"] -= 1
            return

    join_room(room_code)  # Join the room only after all checks have passed.
    if not resumeGame:
        emit("playerAlerts", {"name": username, "message": "has entered the room!", "playerCount": rooms[room_code]["members"], "player1": rooms[room_code]["player1"], "player2": rooms[room_code]["player2"]}, to=room_code)
        print(f"{username} has joined the room {room_code}")
    else:  # In case you have to resume the game:
        emit("start", {"message": "start", "color": color}, to=player["clientID"])
        # Now, restore the game state for them.
        for move in rooms[room_code]["allMoves"]:
            emit("restoreState", {"moveMadeBy": move[0], "source": move[1], "destination": move[2]},
                 to=player["clientID"])


@socketio.on("disconnect")
def disconnect():
    username, room_code = session.get('username'), session.get('room_code')
    leave_room(room_code)

    if room_code in rooms:
        rooms[room_code]["members"] -= 1
        if rooms[room_code]["members"] <= 0:  # If the last member has left the room, then delete the room itself.
            del rooms[room_code]

        else:
            # If the game hasn't already begun, do this.
            if not rooms[room_code]["inProgress"]:
                if rooms[room_code]["player2"]["username"] == username:
                    rooms[room_code]["player2"]["username"] = ""
                    rooms[room_code]["player2"]["clientID"] = ""
                else:
                    rooms[room_code]["player1"]["username"] = rooms[room_code]["player2"]["username"]
                    rooms[room_code]["player1"]["clientID"] = rooms[room_code]["player2"]["clientID"]
                    rooms[room_code]["player2"]["username"] = ""
                    rooms[room_code]["player2"]["clientID"] = ""

            send({"name": username, "message": "has left the room!", "playerCount": rooms[room_code]["members"], "player1": rooms[room_code]["player1"], "player2": rooms[room_code]["player2"]}, to=room_code)
            print(f"{username} has left the room {room_code}")

            # If the game has begun however, then, don't interchange the players. Keep them as is, i.e., don't do anything special in particular.


@socketio.on("game")
def message(data):
    username, room_code = session.get('username'), session.get('room_code')
    if room_code not in rooms:
        return
    if data['data'] == "start":
        startGame(username, room_code)
    else:
        sendPlayOfGame(data)


def sendPlayOfGame(data):
    username, room_code = session.get('username'), session.get('room_code')
    if rooms[room_code]["player1"]["username"] == username:
        moveMadeBy = "White"
    else:
        moveMadeBy = "Black"
    emit("play", {"moveMadeBy": moveMadeBy, "source": data["source"], "destination": data["destination"]}, to=room_code)
    rooms[room_code]["allMoves"] += [[moveMadeBy, data["source"], data["destination"]]]
    print(f"Latest move by {username}'s ({moveMadeBy}) is piece from {data['source']} moved to piece at {data['destination']}")


def startGame(username, room_code):
    # Check if game can be started, and start the game if this is the case.
    if room_code not in rooms:  # if such a room doesn't even exist, just return
        return
    if rooms[room_code]["inProgress"]:  # if game is already running in this room, but for some reason the connect event failed to detect it, then whichever player requested to start the game must be reconnected to it.
        if username == rooms[room_code]["player1"]["username"]:
            player = rooms[room_code]["player1"]
            color = "White"
        elif username == rooms[room_code]["player2"]["username"]:
            player = rooms[room_code]["player2"]
            color = "Black"
        else:  # Some other random player joined. Don't let them start the game.
            return
        emit("start", {"message": "start", "color": color}, to=player["clientID"])
        # Now, restore the game state for them.
        for move in rooms[room_code]["allMoves"]:
            emit("restoreState", {"moveMadeBy": move[0], "source": move[1], "destination": move[2]},
                 to=player["clientID"])
    else:
        emit("start", {"message": "start", "color": "White"}, to=rooms[room_code]["player1"]["clientID"])
        emit("start", {"message": "start", "color": "Black"}, to=rooms[room_code]["player2"]["clientID"])
        rooms[room_code]["inProgress"] = True


@socketio.on("gameOver")
def gameOver(data):
    # For the first player that sends this info to the server (both will), store it in the database. Don't store it for the second player.
    # Close the game div, and reopen the waiting room div.
    username, room_code = session.get('username'), session.get('room_code')
    if rooms[room_code]["whoWon"] == "":
        rooms[room_code]["whoWon"] = data["whoWon"]
        winner = rooms[room_code]["player1"]["username"] if data["whoWon"] == "White" else rooms[room_code]["player2"]["username"]
        loser = rooms[room_code]["player1"]["username"] if data["whoWon"] == "Black" else rooms[room_code]["player2"]["username"]
        outcome = data["outcome"]
        # Update the SQL database as well.
        with sqlite3.connect('Databases/users.db') as database:
            cursor = database.cursor()
            if outcome != "Stalemate":
                cursor.execute("UPDATE USERS SET wins = wins + 1 WHERE username = (?);", winner)
                cursor.execute("UPDATE USERS SET losses = losses + 1 WHERE username = (?);", loser)
            else:
                cursor.execute("UPDATE USERS SET draws = draws + 1 WHERE username IN (?, ?)", (rooms[room_code]["player1"]["username"], rooms[room_code]["player2"]["username"]))
            database.commit()
            rooms[room_code]["inProgress"] = False  # So that they cannot restart the game as soon as they go to the waiting room. They need to wait for the other player to arrive.
            # Also helps in the case where the other player disconnects after the game is over, and another person joins the lobby.
    else:  # If it is the second player sending the same request:
        rooms[room_code]["whoWon"] = ""
        rooms[room_code]["allMoves"] = []

    emit("gameEnded", to=request.sid)


@socketio.on("chat")
def chat(data):
    username, room_code = session.get("username"), session.get("room_code")
    if room_code not in rooms:
        return

    msgContent = {"name": username, "message": data["data"]}
    emit("chat", msgContent, to=room_code)
    rooms[room_code]["messages"].append(msgContent)
    print(f"User {username} in room {room_code} said: {msgContent['message']}")


# Run the flask server
if __name__ == '__main__':
    socketio.run(app, host="0.0.0.0")
