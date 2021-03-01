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
            if data == None:
                self.send_response(400)
                self.end_headers()
                return
            self.send_response(200)
            self.respJSON({'echo': data["data"]})
        elif method == "POST" and path == "/full-echo":
            self.send_response(200)
            for h in self.headers.keys():
                print("Header %s: %s", h, self.headers.get(h))
                self.send_header(h, self.headers.get(h))
            self.respJSON(data)
        else :
            self.send_response(404)
            self.end_headers()
            
    def do_GET(self):
        self.doAny("GET", self.path)
    def do_POST(self):
        self.doAny("POST", self.path)

server = HTTPServer((HOST, PORT), RequestHandler)
print("Server started http://%s:%d" % (HOST, PORT))
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
server.server_close()