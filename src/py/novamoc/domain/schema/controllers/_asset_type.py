from litestar.controller import Controller


class AssetTypeController(Controller):
    path = "/asset-type"

    def read(): ...
