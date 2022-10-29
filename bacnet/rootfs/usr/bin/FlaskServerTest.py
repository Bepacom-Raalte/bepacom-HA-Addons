from flask import Flask

app = Flask(__name__)

@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"



class main:
    app.run(host = '127.0.0.1', debug= True)



if __name__ == 'main':
    main()