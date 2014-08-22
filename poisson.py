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

@app.route('/data')
def data():
    now = datetime.now()
    timestamp = int(time.mktime(now.timetuple()))

    r_conn.incr("events-observed")
    r_conn.set("last-event", timestamp)

    socketio.emit('new-observation',
            {
                'data': 1,
                'count': r_conn.get("events-observed"),
                'timespan': r_conn.get("first-event")
            },
            namespace="/poisson")
    return "OK"

@socketio.on('connect', namespace='/poisson')
def test_connect():
    print "Connected"

if __name__ == '__main__':
    now = datetime.now()
    timestamp = int(time.mktime(now.timetuple()))

    # Setup Redis
    r_conn = Redis("localhost")
    r_conn.set("events-observed", 0)
    r_conn.set("first-event", timestamp)

    # Launch app
    #app.debug = True
    app.host = '0.0.0.0'
    socketio.run(app)
