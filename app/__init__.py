from app.config import Config


def create_app():
    from flask import Flask, render_template

    app = Flask(__name__)
    app.config.from_object(Config)

    from app.api.routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    @app.get('/')
    def index():
        return render_template('index.html')

    return app
