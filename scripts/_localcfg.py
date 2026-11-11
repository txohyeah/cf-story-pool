#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地私有配置读取。

真实账号表、项目名、凭据文件名一律放在 data/local_config.json（**不入库**，
示例见 data/local_config.example.json）。缺失时按环境变量 → 默认占位值回退。
环境变量优先级最高：POOL_USERS(JSON) / POOL_PROJECT_A / POOL_PROJECT_B /
POOL_TEST_PASS_FILE / POOL_DOC_USER / POOL_DOC_PASS_FILE
"""
import json
import os

CFG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'data', 'local_config.json')


def load():
    if os.path.exists(CFG):
        with open(CFG, encoding='utf-8') as f:
            return json.load(f)
    return {}


def get(key, default=None):
    env = os.environ.get('POOL_' + key.upper())
    if env:
        if key == 'users':
            return json.loads(env)
        return env
    return load().get(key, default)
