"""Unit tests for configuration options."""

from oslo_config import cfg

from octavia_loxilb.common import config, constants


def test_config_registration():
    conf = cfg.ConfigOpts()
    config.register_opts(conf)
    assert hasattr(conf, "loxilb")
    opt_map = {opt.name: opt.default for opt in config.LOXILB_OPTS}
    assert opt_map["api_timeout"] == constants.DEFAULT_API_TIMEOUT
    assert opt_map["api_retries"] == constants.DEFAULT_API_RETRIES
    assert opt_map["auth_type"] == constants.AUTH_TYPE_NONE
    assert opt_map["default_nat_mode"] == "onearm"
    assert opt_map["stats_enabled"] is True
    assert opt_map["stats_interval"] == 5


def test_config_validation_success(mock_conf):
    errors = config.validate_config(mock_conf)
    assert errors == []


def test_config_validation_missing_endpoints():
    conf = cfg.ConfigOpts()
    config.register_opts(conf)
    conf.set_override("api_endpoints", [], group="loxilb")
    errors = config.validate_config(conf)
    assert any("api_endpoints" in e for e in errors)


def test_config_validation_invalid_basic_auth():
    conf = cfg.ConfigOpts()
    config.register_opts(conf)
    conf.set_override("auth_type", "password", group="loxilb")
    conf.set_override("username", "", group="loxilb")
    errors = config.validate_config(conf)
    assert any("Basic auth" in e for e in errors)


def test_config_validation_invalid_token_auth():
    conf = cfg.ConfigOpts()
    config.register_opts(conf)
    conf.set_override("auth_type", "token", group="loxilb")
    conf.set_override("api_token", "", group="loxilb")
    errors = config.validate_config(conf)
    assert any("Token auth" in e for e in errors)
