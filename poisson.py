from datetime import datetime
import time

from flask import Flask, render_template
from flask.ext.socketio import SocketIO, emit

from redis import Redis

app = Flask(__name__)
socketio = SocketIO(app)

@app.route('/')
def home():
    return render_template('poisson.html',
            count=r_conn.get("events-observed"))

@app.route('/data/<event_name>')
def data(event_name):
    now = datetime.now()
    timestamp = int(time.mktime(now.timetuple()))

    if event_name not in r_conn.smembers("events"):
        socketio.emit('new-event',
                {
                    'event_name': event_name,
                },
                namespace="/poisson")
        r_conn.sadd("events", event_name)
        r_conn.set(event_name, 0)

    # Increment counters and update timestamp
    r_conn.incr(event_name)
    r_conn.incr("events-observed")
    r_conn.set("last-event", timestamp)

    # Announce new observation to clients
    socketio.emit('new-observation',
            {
                'data': 1,
                'event_name': event_name,
                'count': r_conn.get("events-observed"),
                'timespan': r_conn.get("first-event")
            },
            namespace="/poisson")
    return "OK"

@socketio.on('connected', namespace='/poisson')
def client_connected(message):
    # NOTE sets are not JSON serializable
    members = list(r_conn.smembers("events"))
    flags = {}
    for m in members:
        flags[m] = 0

    socketio.emit('events',
            {
                'id': message["id"],
                'event_members': list(members),
                'event_flags': flags
            },
            namespace="/poisson")
    print ("Client %s Connected. Sent event list." % message["id"])

if __name__ == '__main__':
    now = datetime.now()
    timestamp = int(time.mktime(now.timetuple()))

    # Setup Redis
    r_conn = Redis("localhost")
    r_conn.set("events-observed", 0)
    r_conn.set("first-event", timestamp)

    # Redis event set
    r_conn.delete("events")
    r_conn.sadd("events", "generic")

    # Launch app
    #app.debug = True
    app.host = '0.0.0.0'
    socketio.run(app)
