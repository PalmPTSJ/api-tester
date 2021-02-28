# APT: api-tester

## Quickstart

project/testfile.apitest
```
SECT    Test ping
REQ     GET     https://127.0.0.1:8080/ping
RES     {"$status": 200}

SECT    Test echo
REQ     POST    https://127.0.0.1:8080/echo     {{
    "data": "sample string"
}}
RES     {
    $status: 200
    echo_data: sample string
}
```

## Run with APT runner
```sh
python runner.py project/
```