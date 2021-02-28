import os
import json
import threading
import queue
import time
import requests

# setup test server
HOST = "0.0.0.0"
PORT = 8080

from http.server import HTTPServer, BaseHTTPRequestHandler
class RequestHandler(BaseHTTPRequestHandler):
    def readBody(self):
        contentLength = self.headers.get('content-length')
        return None if contentLength == None or contentLength == "0" else json.loads(self.rfile.read(int(contentLength)))
    def respJSON(self, data):
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def doAny(self, method, path):
        data = self.readBody()
        if method == "GET" and path == "/ping":
            self.send_response(200)
            self.respJSON({'status': 'OK'})
        elif method == "POST" and path == "/echo": # {"data": "ANYTHING"}
            self.send_response(200)
            self.respJSON({'echo': data["data"]})
        else :
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        self.doAny("GET", self.path)
    def do_POST(self):
        self.doAny("POST", self.path)

def Server(q:queue.Queue):
    server = HTTPServer((HOST, PORT), RequestHandler)
    print("Server started http://%s:%d" % (HOST, PORT))
    try:
        q.put("START")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
    print("Server stopped.")

    threading.Thread()

def Test():
    print("Performing test")
    time.sleep(1)
    print("Test done")

# Run
serverStartedQ = queue.Queue(maxsize=0)
serverThread = threading.Thread(target = Server,args=[serverStartedQ], daemon=True) 
serverThread.start()
try :
    serverStartedQ.get(block=True, timeout=2)
except:
    print("Server didn't start within 2 seconds")
    exit(1)
# Try calling until server OK
res = requests.get("http://localhost:8080/ping")
if res.status_code == 200:
    print("Server ping OK")
else:
    print("Server ping not OK")
    exit(1)
Test()