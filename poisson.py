from datetime import datetime
import time
import json

from flask import Flask, render_template, request, Response
from flask_socketio import SocketIO as SIO
from flask_socketio import emit

from redis import Redis

app = Flask(__name__)
socketio = SIO(app)

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


def add_observation(event_name, event_value):
    now = datetime.now()
    timestamp = int(time.mktime(now.timetuple()))

    if event_name not in r_conn.smembers("events"):
        socketio.emit('new-event', {
            'event_name': event_name,
        }, namespace="/poisson")
        # Add the set
        r_conn.sadd("events", event_name)

    # Increment counters and update timestamp
    r_conn.incr(event_name)
    r_conn.incr("events-observed")
    r_conn.set("last-event", timestamp)

    # Push new timestamp record to this event's member list
    r_conn.zadd(event_name+"_ts", timestamp, event_value)

    # Announce new observation to clients
    socketio.emit('new-observation', {
                'data': event_value,
                'event_name': event_name,
                'count': r_conn.get("events-observed"),
                'timespan': r_conn.get("first-event")
    }, namespace="/poisson")

@app.route('/json/', methods=["POST"])
def process_json():
    payload = request.get_json()
    if not payload:
        return Response(json.dumps({"status": "NOTOK"}), status=400, mimetype='application/json')

    for key in payload:
        try:
            add_observation(key, float(payload[key]))
        except ValueError:
            # "OH WELL THAT'S IT, ANOTHER OWL BASED FUCK UP, SAM"
            pass
        except Exception as e:
            print e
            return Response(json.dumps({"status": "NOTOK"}), status=400, mimetype='application/json')
    return Response(json.dumps({"status": "OK"}), status=200, mimetype='application/json')

@app.route('/data/<event_name>', defaults={'value': 1})
@app.route('/data/<event_name>/<value>')
def data(event_name, value):
    try:
        add_observation(event_name, value)
    except Exception as e:
        print(e)
        return Response(json.dumps({"status": "NOTOK"}), status=400, mimetype='application/json')
    return Response(json.dumps({"status": "OK"}), status=200, mimetype='application/json')

@app.route('/reset/')
def reset():
    r_conn.set("events-observed", 0)
    r_conn.set("first-event", timestamp)
    r_conn.delete("last-event")
    r_conn.delete("events")
    return Response(json.dumps({"status": "OK"}), status=200, mimetype='application/json')

@socketio.on('connected', namespace='/poisson')
def client_connected(message):
    # NOTE sets are not JSON serializable
    members = list(r_conn.smembers("events"))
    flags = {}
    for m in members:
        flags[m] = 0

    socketio.emit('events', {
        'id': message["id"],
        'event_members': list(members),
        'event_flags': flags
    }, namespace="/poisson")

    now_stamp = int(time.mktime(datetime.now().timetuple()))
    max_past = now_stamp - STEP_SIZE
    observations = {}
    for event_name in members:
        # TODO Ideally we'd like to send over sparse lists
        observations[event_name] = [0] * STEP_SIZE
        for event_ts, event_value in r_conn.zrange(m+"_ts", 0, -1, withscores=True):
            try:
                observations[event_name][now_stamp - int(event_ts)] = int(event_value)
            except IndexError:
                pass
        observations[event_name] = observations[event_name][::-1]

    socketio.emit('observations', {
        'id': message["id"],
        'observations' : observations
    }, namespace="/poisson")
    print ("Client %s Connected. Sent event list and observations." % message["id"])
    return Response(json.dumps({"status": "OK"}), status=200, mimetype='application/json')


# Do it
now = datetime.now()
timestamp = int(time.mktime(now.timetuple()))

# Setup Redis
r_conn = Redis("localhost")

if __name__ == '__main__':
    # Launch app
    #app.debug = True
    socketio.run(app)
