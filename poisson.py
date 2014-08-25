from datetime import datetime
import time

from flask import Flask, render_template
from flask.ext.socketio import SocketIO, emit

from redis import Redis

app = Flask(__name__)
socketio = SocketIO(app)

STEP_SIZE = 960 # Number of events to display (send to client) on load

@app.route('/')
def home():
    last_event = r_conn.get("last-event")
    if last_event is None:
        last_event = "Never"
    return render_template('poisson.html',
            count=r_conn.get("events-observed"),
            last_event=last_event,
            first_event=r_conn.get("first-event"))

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
        r_conn.delete(event_name+"_set")

    # Increment counters and update timestamp
    r_conn.incr(event_name)
    r_conn.incr("events-observed")
    r_conn.set("last-event", timestamp)

    # Push new timestamp record to this event's member list
    r_conn.sadd(event_name+"_set", timestamp)

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

    now_stamp = int(time.mktime(datetime.now().timetuple()))
    max_past = now_stamp - STEP_SIZE
    observations = {}
    for m in members:
        m_obs = sorted(r_conn.smembers(m+"_set"))

        # TODO Ideally we'd like to send over sparse lists
        observations[m] = [0] * STEP_SIZE
        for o in m_obs:
            o = int(o)
            observations[m][now_stamp - o] = 1
            if o < max_past:
                break
        observations[m] = observations[m][::-1]

    socketio.emit('observations',
            {
                'id': message["id"],
                'observations' : observations
            },
            namespace="/poisson")
    print ("Client %s Connected. Sent event list and observations." % message["id"])

if __name__ == '__main__':
    now = datetime.now()
    timestamp = int(time.mktime(now.timetuple()))

    # Setup Redis
    r_conn = Redis("localhost")
    r_conn.set("events-observed", 0)
    r_conn.set("first-event", timestamp)
    r_conn.delete("last-event")

    # Redis event set
    r_conn.delete("events")

    # Launch app
    #app.debug = True
    app.host = '0.0.0.0'
    socketio.run(app)
