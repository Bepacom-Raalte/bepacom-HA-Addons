
from flask import Flask

app = Flask(__name__)

@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"


def main():
    while True:
        app.run(host = '0.0.0.0' ,port=7813, debug= True, use_reloader=False)


if __name__ == "__main__":
    main()