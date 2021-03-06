from datetime import datetime
from datetime import timedelta
import time
import json
import math

from flask import Flask, render_template, request, Response
from flask_socketio import SocketIO as SIO
from flask_socketio import emit

from redis import Redis
from redis.exceptions import ResponseError

from config import EVENT_CONFIGS, EVENT_ORDER, EVENT_AUTH_KEY

app = Flask(__name__)
socketio = SIO(app)

MAX_EVENTS = 945 # Number of events to display (send to client) on load
STEP_seconds = 2*60
TIMESPAN = MAX_EVENTS * STEP_seconds

MINIMAX_EVENTS = 165
MINISTEP_seconds = 30

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
        #print("[EVE] %s" % (event_name))

    # Increment counters and update timestamp
    r_conn.incr(event_name)
    r_conn.incr("events-observed")
    r_conn.set("last-event", timestamp)

    # Push new timestamp record to this event's member list
    r_conn.zadd(event_name+"_ts", timestamp, event_value)

    if float(event_value) == 0:
        event_value = 0.001

    # Announce new observation to clients
    socketio.emit('new-observation', {
                'data': event_value,
                'event_name': event_name,
                'count': r_conn.get("events-observed"),
                'timespan': r_conn.get("first-event")
    }, namespace="/poisson")
    #print("[OBS] %s:%s" % (event_name, str(event_value)))

@app.route('/json/', methods=["POST"])
def process_json():
    msg_list = []
    payload = request.get_json()
    if not payload:
        return Response(json.dumps({"status": "NOTOK"}), status=400, mimetype='application/json')
    if EVENT_AUTH_KEY not in payload:
        return Response(json.dumps({"status": "NOTOK"}), status=403, mimetype='application/json')

    for key in payload:
        try:
            add_observation(key, float(payload[key]))
        except ValueError:
            # "OH WELL THAT'S IT, ANOTHER OWL BASED FUCK UP, SAM"
            pass
        except ResponseError as e:
            # "value is not a valid float" after unplugged 
            msg_list.append("%s: %s" % key, str(e))
            pass
        except Exception as e:
            #return Response(json.dumps({"status": "NOTOK"}), status=400, mimetype='application/json')
            pass
    return Response(json.dumps({"status": "OK", "messages": msg_list}), status=200, mimetype='application/json')

@app.route('/data/<event_name>', defaults={'value': 1})
@app.route('/data/<event_name>/<value>')
def data(event_name, value):
    #try:
    #    add_observation(event_name, value)
    #except Exception as e:
    #    print(e)
    #    return Response(json.dumps({"status": "NOTOK"}), status=400, mimetype='application/json')
    #return Response(json.dumps({"status": "OK"}), status=200, mimetype='application/json')
    return Response(json.dumps({"status": "NOTOK"}), status=403, mimetype='application/json')

@app.route('/reset/')
def reset():
    #r_conn.set("events-observed", 0)
    #r_conn.set("first-event", timestamp)
    #r_conn.delete("last-event")
    #members = list(r_conn.smembers("events"))
    #for m in members:
    #    r_conn.delete(m+"_ts")
    #r_conn.delete("events")
    #return Response(json.dumps({"status": "OK"}), status=200, mimetype='application/json')
    return Response(json.dumps({"status": "NOTOK"}), status=403, mimetype='application/json')

@socketio.on('connected', namespace='/poisson')
def client_connected(message):
    # NOTE sets are not JSON serializable
    members = list(r_conn.smembers("events"))

    current_dt = datetime.now()
    current_dt.replace(second=int(math.floor(current_dt.second/30)*30), microsecond=0)
    resolution = timedelta(seconds=30)
    current_ts = int(current_dt.strftime('%s'))
    start_ts = current_ts - TIMESPAN

    observations = {}
    mini_observations = {}

    events_sorted = EVENT_ORDER[:]
    events_seen = []
    events_to_add = []

    for event_name in members:
        if event_name not in EVENT_ORDER:
            events_to_add.append(event_name)
        events_seen.append(event_name)

    # Remove missing events
    missing_events = set(events_sorted) - set(events_seen)
    for missing in missing_events:
        events_sorted.remove(missing)

    # Add missing events
    events_sorted.extend(events_to_add)

    flags = {}
    for i, event_name in enumerate(events_sorted):
        flags[event_name] = 0
        # TODO Ideally we'd like to send over sparse lists
        observations[event_name] = [0] * MAX_EVENTS
        mini_observations[event_name] = [0] * MINIMAX_EVENTS
        keys = r_conn.zrangebylex(event_name+"_ts", '['+str(start_ts), '['+str(current_ts))
        first_key = r_conn.zrank(event_name+"_ts", keys[-1])
        for event_ts, event_value in r_conn.zrange(event_name+"_ts", -(first_key), -1, withscores=True):
            step_bin = int(math.floor((current_ts - int(event_ts)) / STEP_seconds))
            mini_step_bin = int(math.floor((current_ts - int(event_ts)) / MINISTEP_seconds))
            if step_bin < 0:
                continue
            try:
                event_value = float(event_value)
                if event_value == 0:
                    event_value = 0.0001
                observations[event_name][step_bin] = event_value
                mini_observations[event_name][mini_step_bin] = event_value
            except IndexError:
                pass
        observations[event_name] = observations[event_name][::-1]
        mini_observations[event_name] = mini_observations[event_name][::-1]

    socketio.emit('observations', {
        'id': message["id"],
        'observations' : observations,
        'observations_mini' : mini_observations,
        'event_members': events_sorted,
        'event_configs': EVENT_CONFIGS,
        'event_flags': flags,
    }, namespace="/poisson")
    print ("Client %s Connected. Sent event list and observations." % message["id"])
    #return Response(json.dumps({"status": "OK"}), status=200, mimetype='application/json')


# Do it
now = datetime.now()
timestamp = int(time.mktime(now.timetuple()))

# Setup Redis
r_conn = Redis("localhost")

if __name__ == '__main__':
    # Launch app
    #app.debug = True
    socketio.run(app)
