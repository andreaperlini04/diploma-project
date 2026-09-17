from flask import Flask, request


def register_cors(app: Flask) -> None:
    """Header CORS per il JS del plugin Moodle, servito da un'origine diversa.

    Access-Control-Allow-Origin non ammette una lista: si rimanda indietro
    l'Origin della richiesta se è fra quelle configurate."""

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin")
        if origin and origin in app.config["ALLOWED_ORIGINS"]:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response