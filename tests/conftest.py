import pytest


def pytest_addoption(parser):
    parser.addoption('--deployment', action='store_true', help='Run real TCP/TLS/nginx acceptance; requires nginx, openssl and ffmpeg')


def pytest_configure(config):
    config.addinivalue_line('markers', 'deployment: real proxy and service-process acceptance using an isolated test database')


def pytest_collection_modifyitems(config, items):
    if not config.getoption('--deployment'):
        for item in items:
            if 'deployment' in item.keywords:
                item.add_marker(pytest.mark.skip(reason='enable --deployment to run the real proxy acceptance'))
