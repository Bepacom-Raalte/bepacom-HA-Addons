from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from flask import Flask, jsonify, escape, request, render_template


#===================================================
# Flask setup (WebUI)
#===================================================
flask_app = Flask("WebUI")

@flask_app.route("/")
def flask_main():
    return render_template("index.html")


#===================================================
# FastAPI setup
#===================================================
app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/nice")
async def nicepage():
    return "<p>henlo</p>"

# mounting flask into FastAPI
app.mount("/webapp", WSGIMiddleware(flask_app))
