import base64
import hashlib
import hmac
import time
import json
import requests
from datetime import datetime


class JDApi:
    def __init__(self,
                 app_key,
                 app_secret,
                 access_token,
                 base_uri="https://api.jdl.com",
                 domain="ECAP",
                 algorithm="md5-salt"
                 ):
        self.base_uri = base_uri
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token = access_token
        self.domain = domain
        self.algorithm = algorithm

    @property
    def headers(self):
        offset = str(int(-time.timezone / 3600))
        headers = {
            "lop-tz": offset,  # lop-tz代表时区，为接口调用当地的时区；删去后默认为东八区
            "User-Agent": "lop-http/python3",  # 用于开放平台识别客户调用API方式，客户无需修改
            "content-type": "application/json;charset=utf-8",
        }
        return headers

    @staticmethod
    def sign(algorithm: str, data: bytes, secret: bytes) -> str:
        if algorithm == "md5-salt":
            h = hashlib.md5()
            h.update(data)
            return h.digest().hex()
        elif algorithm == "HMacMD5":
            return base64.b64encode(hmac.new(secret, data, hashlib.md5).digest()).decode("UTF-8")
        elif algorithm == "HMacSHA1":
            return base64.b64encode(hmac.new(secret, data, hashlib.sha1).digest()).decode("UTF-8")
        elif algorithm == "HMacSHA256":
            return base64.b64encode(hmac.new(secret, data, hashlib.sha256).digest()).decode("UTF-8")
        elif algorithm == "HMacSHA512":
            return base64.b64encode(hmac.new(secret, data, hashlib.sha512).digest()).decode("UTF-8")
        raise NotImplemented("Algorithm " + algorithm + " not supported yet")

    def compute_params(self, body, path):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = "".join([
            self.app_secret,
            "access_token", self.access_token,
            "app_key", self.app_key,
            "method", path,
            "param_json", body,
            "timestamp", timestamp,
            "v", "2.0",
            self.app_secret,
        ])
        sign_ = self.sign(self.algorithm, content.encode("UTF-8"), self.app_secret.encode("UTF-8"))
        queries = {
            "LOP-DN": self.domain,
            "app_key": self.app_key,
            "access_token": self.access_token,
            "timestamp": timestamp,
            "v": "2.0",
            "sign": sign_,
            "algorithm": self.algorithm
        }
        return queries

    def _request(self, path, data, method='POST'):
        uri = self.base_uri + path
        body = json.dumps(data, indent=4, ensure_ascii=False)
        response = requests.request(method, uri, params=self.compute_params(body, path), data=body.encode("UTF-8"),
                                    headers=self.headers)
        return response

    def orders_create(self, data):
        path = "/ecap/v1/orders/create"
        return self._request(path, data)

    def orders_cancel(self, data):
        path = "/ecap/v1/orders/cancel"
        return self._request(path, data)

    def orders_actualfee_query(self, data):
        path = "/ecap/v1/orders/actualfee/query"
        return self._request(path, data)
