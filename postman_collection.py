""" Postman collection

Export postman collection into files and folders

Import postman collection from folder into a postman collection file

"""

import json
import os

def LoadPostmanCollection(postmanCollectionFile: str, outputDir: str) :
    def WriteJSON(filepath:str, filename:str, data:dict):
        os.makedirs(filepath, exist_ok=True)
        fullpath = os.path.join(filepath, filename)
        print(fullpath, json.dumps(data, indent=2), "\n")
        with open(fullpath, "w+") as f:
            f.write(json.dumps(data, indent=2))

    def DoItem(nowpath:str, data:dict):
        if "item" in data: # Item group
            for item in data["item"]:
                DoItem(os.path.join(nowpath, data["name"]), item)
            del data["item"]
            WriteJSON(os.path.join(nowpath, data["name"]), "_folder.json", data)
        else:
            WriteJSON(os.path.join(nowpath), data["name"] + ".json", data)

    with open(postmanCollectionFile, "r") as pm:
        data = json.loads(pm.read())

        # Print collection info
        WriteJSON(outputDir, "_collection.json", data["info"])

        for item in data["item"]:
            DoItem(outputDir, item)

def SavePostmanCollection(postmanCollectionFile: str, inputDir: str):
    def ReadJSON(file:str) -> dict:
        with open(file, "r") as f:
            return json.loads(f.read())

    def ReadDir(dirname:str):
        data = {
            "item": []
        }
        root, dirs, files = next(os.walk(dirname))
        for fname in files:
            if fname == "_collection.json":  data.update({"info": ReadJSON(os.path.join(root, fname))})
            elif fname == "_folder.json":   data.update(ReadJSON(os.path.join(root, fname)))
            else:                           data["item"].append(ReadJSON(os.path.join(root, fname)))
        for subdirname in dirs:
            data["item"].append(ReadDir(os.path.join(root, subdirname)))
        return data

    with open(postmanCollectionFile, "w+") as f:
        f.write(json.dumps(ReadDir(inputDir), indent=2))

# LoadPostmanCollection("Test Collection.postman_collection.json", "test_collection")

SavePostmanCollection("test_output.postman_collection.json", "test_collection")