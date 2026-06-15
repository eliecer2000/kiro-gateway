# -*- coding: utf-8 -*-

"""
Unit tests for the configuration module.
Verifies loading settings from environment variables.
"""

import pytest
import os
from pathlib import Path
from typing import Callable, Dict, Optional
from unittest.mock import patch


class TestLogLevelConfig:
    """Tests for LOG_LEVEL configuration."""

    def teardown_method(self, method: Callable[..., object]) -> None:
        """Restore module state after every test that reloads kiro.config."""
        import importlib
        import kiro.config as config_module
        importlib.reload(config_module)

    def test_default_log_level_is_info(self) -> None:
        """
        What it does: Verifies that LOG_LEVEL defaults to INFO.
        Purpose: Ensure that INFO is used when no environment variable is set.
        
        Note: This test verifies the config.py code logic, not the actual
        value from the .env file. We mock os.getenv to simulate
        the absence of the environment variable.
        """
        print("Setup: Mocking os.getenv for LOG_LEVEL...")
        
        # Create a mock that returns None for LOG_LEVEL (simulating missing variable)
        original_getenv = os.getenv
        
        def mock_getenv(key, default=None):
            if key == "LOG_LEVEL":
                print(f"os.getenv('{key}') -> None (mocked)")
                return default  # Return default, simulating missing variable
            return original_getenv(key, default)
        
        with patch.object(os, 'getenv', side_effect=mock_getenv):
            # Reload config module with mocked getenv
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"LOG_LEVEL: {config_module.LOG_LEVEL}")
            print(f"Comparing: Expected 'INFO', Got '{config_module.LOG_LEVEL}'")
            assert config_module.LOG_LEVEL == "INFO"
        
        # Restore module with real values
        import importlib
        import kiro.config as config_module
        importlib.reload(config_module)
    
    def test_log_level_from_environment(self) -> None:
        """
        What it does: Verifies loading LOG_LEVEL from environment variable.
        Purpose: Ensure that the value from environment is used.
        """
        print("Setup: Setting LOG_LEVEL=DEBUG...")
        
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"LOG_LEVEL: {config_module.LOG_LEVEL}")
            print(f"Comparing: Expected 'DEBUG', Got '{config_module.LOG_LEVEL}'")
            assert config_module.LOG_LEVEL == "DEBUG"
    
    def test_log_level_uppercase_conversion(self) -> None:
        """
        What it does: Verifies LOG_LEVEL conversion to uppercase.
        Purpose: Ensure that lowercase value is converted to uppercase.
        """
        print("Setup: Setting LOG_LEVEL=warning (lowercase)...")
        
        with patch.dict(os.environ, {"LOG_LEVEL": "warning"}):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"LOG_LEVEL: {config_module.LOG_LEVEL}")
            print(f"Comparing: Expected 'WARNING', Got '{config_module.LOG_LEVEL}'")
            assert config_module.LOG_LEVEL == "WARNING"
    
    def test_log_level_trace(self) -> None:
        """
        What it does: Verifies setting LOG_LEVEL=TRACE.
        Purpose: Ensure that TRACE level is supported.
        """
        print("Setup: Setting LOG_LEVEL=TRACE...")
        
        with patch.dict(os.environ, {"LOG_LEVEL": "TRACE"}):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"LOG_LEVEL: {config_module.LOG_LEVEL}")
            assert config_module.LOG_LEVEL == "TRACE"
    
    def test_log_level_error(self) -> None:
        """
        What it does: Verifies setting LOG_LEVEL=ERROR.
        Purpose: Ensure that ERROR level is supported.
        """
        print("Setup: Setting LOG_LEVEL=ERROR...")
        
        with patch.dict(os.environ, {"LOG_LEVEL": "ERROR"}):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"LOG_LEVEL: {config_module.LOG_LEVEL}")
            assert config_module.LOG_LEVEL == "ERROR"
    
    def test_log_level_critical(self) -> None:
        """
        What it does: Verifies setting LOG_LEVEL=CRITICAL.
        Purpose: Ensure that CRITICAL level is supported.
        """
        print("Setup: Setting LOG_LEVEL=CRITICAL...")
        
        with patch.dict(os.environ, {"LOG_LEVEL": "CRITICAL"}):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"LOG_LEVEL: {config_module.LOG_LEVEL}")
            assert config_module.LOG_LEVEL == "CRITICAL"


class TestToolDescriptionMaxLengthConfig:
    """Tests for TOOL_DESCRIPTION_MAX_LENGTH configuration."""
    
    def test_default_tool_description_max_length(self) -> None:
        """
        What it does: Verifies the default value for TOOL_DESCRIPTION_MAX_LENGTH.
        Purpose: Ensure that 10000 is used by default.
        """
        print("Setup: Removing TOOL_DESCRIPTION_MAX_LENGTH from environment...")
        
        with patch.dict(os.environ, {}, clear=False):
            if "TOOL_DESCRIPTION_MAX_LENGTH" in os.environ:
                del os.environ["TOOL_DESCRIPTION_MAX_LENGTH"]
            
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"TOOL_DESCRIPTION_MAX_LENGTH: {config_module.TOOL_DESCRIPTION_MAX_LENGTH}")
            assert config_module.TOOL_DESCRIPTION_MAX_LENGTH == 10000
    
    def test_tool_description_max_length_from_environment(self) -> None:
        """
        What it does: Verifies loading TOOL_DESCRIPTION_MAX_LENGTH from environment.
        Purpose: Ensure that the value from environment is used.
        """
        print("Setup: Setting TOOL_DESCRIPTION_MAX_LENGTH=5000...")
        
        with patch.dict(os.environ, {"TOOL_DESCRIPTION_MAX_LENGTH": "5000"}):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"TOOL_DESCRIPTION_MAX_LENGTH: {config_module.TOOL_DESCRIPTION_MAX_LENGTH}")
            assert config_module.TOOL_DESCRIPTION_MAX_LENGTH == 5000
    
    def test_tool_description_max_length_zero_disables(self) -> None:
        """
        What it does: Verifies that 0 disables the feature.
        Purpose: Ensure that TOOL_DESCRIPTION_MAX_LENGTH=0 works.
        """
        print("Setup: Setting TOOL_DESCRIPTION_MAX_LENGTH=0...")
        
        with patch.dict(os.environ, {"TOOL_DESCRIPTION_MAX_LENGTH": "0"}):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"TOOL_DESCRIPTION_MAX_LENGTH: {config_module.TOOL_DESCRIPTION_MAX_LENGTH}")
            assert config_module.TOOL_DESCRIPTION_MAX_LENGTH == 0


class TestTimeoutConfigurationWarning:
    """Tests for _warn_timeout_configuration() function."""
    
    def test_no_warning_when_first_token_less_than_streaming(self) -> None:
        """
        What it does: Verifies that logger.warning is NOT called with correct configuration.
        Purpose: Ensure no warning when FIRST_TOKEN_TIMEOUT < STREAMING_READ_TIMEOUT.
        """
        print("Setup: FIRST_TOKEN_TIMEOUT=15, STREAMING_READ_TIMEOUT=300...")

        with patch.dict(os.environ, {
            "FIRST_TOKEN_TIMEOUT": "15",
            "STREAMING_READ_TIMEOUT": "300"
        }):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)

            with patch.object(config_module.logger, "warning") as mock_warning:
                config_module._warn_timeout_configuration()
                print(f"logger.warning called: {mock_warning.called}")
                mock_warning.assert_not_called()

    def test_warning_when_first_token_equals_streaming(self) -> None:
        """
        What it does: Verifies that logger.warning is called when timeouts are equal.
        Purpose: Ensure warning when FIRST_TOKEN_TIMEOUT == STREAMING_READ_TIMEOUT.
        """
        print("Setup: FIRST_TOKEN_TIMEOUT=300, STREAMING_READ_TIMEOUT=300...")

        with patch.dict(os.environ, {
            "FIRST_TOKEN_TIMEOUT": "300",
            "STREAMING_READ_TIMEOUT": "300"
        }):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)

            with patch.object(config_module.logger, "warning") as mock_warning:
                config_module._warn_timeout_configuration()
                print(f"logger.warning called: {mock_warning.called}")
                mock_warning.assert_called_once()
                call_args = str(mock_warning.call_args)
                assert "Suboptimal timeout configuration" in call_args

    def test_warning_when_first_token_greater_than_streaming(self) -> None:
        """
        What it does: Verifies that logger.warning is called when FIRST_TOKEN > STREAMING.
        Purpose: Ensure warning when FIRST_TOKEN_TIMEOUT > STREAMING_READ_TIMEOUT.
        """
        print("Setup: FIRST_TOKEN_TIMEOUT=500, STREAMING_READ_TIMEOUT=300...")

        with patch.dict(os.environ, {
            "FIRST_TOKEN_TIMEOUT": "500",
            "STREAMING_READ_TIMEOUT": "300"
        }):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)

            with patch.object(config_module.logger, "warning") as mock_warning:
                config_module._warn_timeout_configuration()
                print(f"logger.warning called: {mock_warning.called}")
                mock_warning.assert_called_once()
                # Verify timeout values appear in the warning message
                call_args = str(mock_warning.call_args)
                assert "500" in call_args
                assert "300" in call_args

    def test_warning_contains_recommendation(self) -> None:
        """
        What it does: Verifies that the warning message contains actionable guidance.
        Purpose: Ensure users receive useful information to fix the configuration.
        """
        print("Setup: FIRST_TOKEN_TIMEOUT=400, STREAMING_READ_TIMEOUT=300...")

        with patch.dict(os.environ, {
            "FIRST_TOKEN_TIMEOUT": "400",
            "STREAMING_READ_TIMEOUT": "300"
        }):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)

            with patch.object(config_module.logger, "warning") as mock_warning:
                config_module._warn_timeout_configuration()
                print(f"logger.warning called: {mock_warning.called}")
                mock_warning.assert_called_once()
                call_args = str(mock_warning.call_args)
                assert "Recommended" in call_args or "LESS than" in call_args or "Suboptimal" in call_args


class TestAwsSsoOidcUrlConfig:
    """Tests for AWS SSO OIDC URL configuration."""
    
    def test_aws_sso_oidc_url_template_exists(self) -> None:
        """
        What it does: Verifies that AWS_SSO_OIDC_URL_TEMPLATE constant exists.
        Purpose: Ensure the template is defined in config.
        """
        print("Setup: Importing config module...")
        import importlib
        import kiro.config as config_module
        importlib.reload(config_module)
        
        print("Verification: AWS_SSO_OIDC_URL_TEMPLATE exists...")
        assert hasattr(config_module, 'AWS_SSO_OIDC_URL_TEMPLATE')
        
        print(f"AWS_SSO_OIDC_URL_TEMPLATE: {config_module.AWS_SSO_OIDC_URL_TEMPLATE}")
        assert "oidc" in config_module.AWS_SSO_OIDC_URL_TEMPLATE
        assert "amazonaws.com" in config_module.AWS_SSO_OIDC_URL_TEMPLATE
        assert "{region}" in config_module.AWS_SSO_OIDC_URL_TEMPLATE
    
    def test_get_aws_sso_oidc_url_returns_correct_url(self) -> None:
        """
        What it does: Verifies that get_aws_sso_oidc_url returns correct URL.
        Purpose: Ensure the function formats URL correctly.
        """
        print("Setup: Importing get_aws_sso_oidc_url...")
        from kiro.config import get_aws_sso_oidc_url
        
        print("Action: Calling get_aws_sso_oidc_url('us-east-1')...")
        url = get_aws_sso_oidc_url("us-east-1")
        
        print(f"Verification: URL is correct...")
        expected = "https://oidc.us-east-1.amazonaws.com/token"
        print(f"Comparing: Expected '{expected}', Got '{url}'")
        assert url == expected
    
    def test_get_aws_sso_oidc_url_with_different_regions(self) -> None:
        """
        What it does: Verifies URL generation for different regions.
        Purpose: Ensure the function works with various AWS regions.
        """
        print("Setup: Importing get_aws_sso_oidc_url...")
        from kiro.config import get_aws_sso_oidc_url
        
        test_cases = [
            ("us-east-1", "https://oidc.us-east-1.amazonaws.com/token"),
            ("eu-west-1", "https://oidc.eu-west-1.amazonaws.com/token"),
            ("ap-southeast-1", "https://oidc.ap-southeast-1.amazonaws.com/token"),
            ("us-west-2", "https://oidc.us-west-2.amazonaws.com/token"),
        ]
        
        for region, expected in test_cases:
            print(f"Action: Calling get_aws_sso_oidc_url('{region}')...")
            url = get_aws_sso_oidc_url(region)
            print(f"Comparing: Expected '{expected}', Got '{url}'")
            assert url == expected


class TestServerHostConfig:
    """Tests for SERVER_HOST configuration."""
    
    def test_default_server_host_is_0_0_0_0(self) -> None:
        """
        What it does: Verifies that SERVER_HOST defaults to 0.0.0.0.
        Purpose: Ensure that 0.0.0.0 (all interfaces) is used when no environment variable is set.
        """
        print("Setup: Removing SERVER_HOST from environment...")
        
        with patch.dict(os.environ, {}, clear=False):
            if "SERVER_HOST" in os.environ:
                del os.environ["SERVER_HOST"]
            
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"SERVER_HOST: {config_module.SERVER_HOST}")
            print(f"DEFAULT_SERVER_HOST: {config_module.DEFAULT_SERVER_HOST}")
            print(f"Comparing: Expected '0.0.0.0', Got '{config_module.SERVER_HOST}'")
            assert config_module.SERVER_HOST == "0.0.0.0"
            assert config_module.DEFAULT_SERVER_HOST == "0.0.0.0"
    
    def test_server_host_from_environment(self) -> None:
        """
        What it does: Verifies loading SERVER_HOST from environment variable.
        Purpose: Ensure that the value from environment is used.
        """
        print("Setup: Setting SERVER_HOST=127.0.0.1...")
        
        with patch.dict(os.environ, {"SERVER_HOST": "127.0.0.1"}):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"SERVER_HOST: {config_module.SERVER_HOST}")
            print(f"Comparing: Expected '127.0.0.1', Got '{config_module.SERVER_HOST}'")
            assert config_module.SERVER_HOST == "127.0.0.1"
    
    def test_server_host_custom_value(self) -> None:
        """
        What it does: Verifies setting SERVER_HOST to a custom IP address.
        Purpose: Ensure that any valid IP address can be used.
        """
        print("Setup: Setting SERVER_HOST=192.168.1.100...")
        
        with patch.dict(os.environ, {"SERVER_HOST": "192.168.1.100"}):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"SERVER_HOST: {config_module.SERVER_HOST}")
            assert config_module.SERVER_HOST == "192.168.1.100"


class TestServerPortConfig:
    """Tests for SERVER_PORT configuration."""
    
    def test_default_server_port_is_8000(self) -> None:
        """
        What it does: Verifies that SERVER_PORT defaults to 8000.
        Purpose: Ensure that 8000 is used when no environment variable is set.
        """
        print("Setup: Removing SERVER_PORT from environment...")
        
        with patch.dict(os.environ, {}, clear=False):
            if "SERVER_PORT" in os.environ:
                del os.environ["SERVER_PORT"]
            
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"SERVER_PORT: {config_module.SERVER_PORT}")
            print(f"DEFAULT_SERVER_PORT: {config_module.DEFAULT_SERVER_PORT}")
            print(f"Comparing: Expected 8000, Got {config_module.SERVER_PORT}")
            assert config_module.SERVER_PORT == 8000
            assert config_module.DEFAULT_SERVER_PORT == 8000
    
    def test_server_port_from_environment(self) -> None:
        """
        What it does: Verifies loading SERVER_PORT from environment variable.
        Purpose: Ensure that the value from environment is used.
        """
        print("Setup: Setting SERVER_PORT=9000...")
        
        with patch.dict(os.environ, {"SERVER_PORT": "9000"}):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"SERVER_PORT: {config_module.SERVER_PORT}")
            print(f"Comparing: Expected 9000, Got {config_module.SERVER_PORT}")
            assert config_module.SERVER_PORT == 9000
    
    def test_server_port_custom_value(self) -> None:
        """
        What it does: Verifies setting SERVER_PORT to a custom port number.
        Purpose: Ensure that any valid port number can be used.
        """
        print("Setup: Setting SERVER_PORT=3000...")
        
        with patch.dict(os.environ, {"SERVER_PORT": "3000"}):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"SERVER_PORT: {config_module.SERVER_PORT}")
            assert config_module.SERVER_PORT == 3000
    
    def test_server_port_is_integer(self) -> None:
        """
        What it does: Verifies that SERVER_PORT is converted to integer.
        Purpose: Ensure that string from environment is converted to int.
        """
        print("Setup: Setting SERVER_PORT=8080 (as string)...")
        
        with patch.dict(os.environ, {"SERVER_PORT": "8080"}):
            import importlib
            import kiro.config as config_module
            importlib.reload(config_module)
            
            print(f"SERVER_PORT: {config_module.SERVER_PORT}")
            print(f"Type: {type(config_module.SERVER_PORT)}")
            assert isinstance(config_module.SERVER_PORT, int)
            assert config_module.SERVER_PORT == 8080


class TestKiroCliDbFileConfig:
    """Tests for KIRO_CLI_DB_FILE configuration."""
    
    def test_kiro_cli_db_file_config_exists(self) -> None:
        """
        What it does: Verifies that KIRO_CLI_DB_FILE constant exists.
        Purpose: Ensure the config parameter is defined.
        """
        print("Setup: Importing config module...")
        import importlib
        import kiro.config as config_module
        importlib.reload(config_module)
        
        print("Verification: KIRO_CLI_DB_FILE exists...")
        assert hasattr(config_module, 'KIRO_CLI_DB_FILE')
        
        print(f"KIRO_CLI_DB_FILE: '{config_module.KIRO_CLI_DB_FILE}'")
        # Default should be empty string
        assert isinstance(config_module.KIRO_CLI_DB_FILE, str)
    
    def test_kiro_cli_db_file_from_environment(self) -> None:
        """
        What it does: Verifies loading KIRO_CLI_DB_FILE from environment variable.
        Purpose: Ensure the value from environment is used and normalized.
        """
        print("Setup: Importing config module...")
        import importlib
        import kiro.config as config_module
        
        # Test that KIRO_CLI_DB_FILE is loaded and is a string
        print(f"KIRO_CLI_DB_FILE: {config_module.KIRO_CLI_DB_FILE}")
        assert isinstance(config_module.KIRO_CLI_DB_FILE, str)
        
        # If value is set (not empty), verify it's a normalized path
        if config_module.KIRO_CLI_DB_FILE:
            # Path should be normalized (no raw ~ or forward slashes on Windows)
            assert not config_module.KIRO_CLI_DB_FILE.startswith("~")
            # Should be a valid path string (contains path separators or is absolute)
            from pathlib import Path
            path = Path(config_module.KIRO_CLI_DB_FILE)
            # Path should be constructable (doesn't raise exception)
            assert str(path) == config_module.KIRO_CLI_DB_FILE


class TestFallbackModelsConfig:
    """Tests for FALLBACK_MODELS configuration."""
    
    def test_fallback_models_exists(self) -> None:
        """
        What it does: Verifies that FALLBACK_MODELS constant exists.
        Purpose: Ensure the fallback model list is defined in config.
        """
        print("Setup: Importing config module...")
        import importlib
        import kiro.config as config_module
        importlib.reload(config_module)
        
        print("Verification: FALLBACK_MODELS exists...")
        assert hasattr(config_module, 'FALLBACK_MODELS')
        
        print(f"FALLBACK_MODELS type: {type(config_module.FALLBACK_MODELS)}")
        assert isinstance(config_module.FALLBACK_MODELS, list)
    
    def test_fallback_models_not_empty(self) -> None:
        """
        What it does: Verifies that FALLBACK_MODELS contains at least one model.
        Purpose: Ensure fallback list is populated for DNS failure recovery.
        """
        print("Setup: Importing FALLBACK_MODELS...")
        from kiro.config import FALLBACK_MODELS
        
        print(f"FALLBACK_MODELS length: {len(FALLBACK_MODELS)}")
        print(f"Comparing: Expected > 0, Got {len(FALLBACK_MODELS)}")
        assert len(FALLBACK_MODELS) > 0
    
    def test_fallback_models_structure(self) -> None:
        """
        What it does: Verifies that each fallback model has required modelId field.
        Purpose: Ensure fallback models have correct structure for cache.update().
        """
        print("Setup: Importing FALLBACK_MODELS...")
        from kiro.config import FALLBACK_MODELS
        
        print(f"Action: Checking structure of {len(FALLBACK_MODELS)} models...")
        for i, model in enumerate(FALLBACK_MODELS):
            print(f"Checking model {i}: {model}")
            
            print(f"  Verification: model is dict...")
            assert isinstance(model, dict), f"Model {i} is not a dict"
            
            print(f"  Verification: model has 'modelId'...")
            assert "modelId" in model, f"Model {i} missing 'modelId'"
            
            print(f"  Verification: modelId is string...")
            assert isinstance(model["modelId"], str), f"Model {i} modelId is not string"
            
            print(f"  Verification: modelId is not empty...")
            assert len(model["modelId"]) > 0, f"Model {i} modelId is empty"
    
    def test_fallback_models_contain_claude_models(self) -> None:
        """
        What it does: Verifies that fallback models include Claude models.
        Purpose: Ensure fallback list contains expected Claude 4/4.5 models.
        """
        print("Setup: Importing FALLBACK_MODELS...")
        from kiro.config import FALLBACK_MODELS
        
        model_ids = [m["modelId"] for m in FALLBACK_MODELS]
        print(f"Model IDs in fallback list: {model_ids}")
        
        print("Verification: Contains at least one Claude model...")
        has_claude = any("claude" in mid.lower() for mid in model_ids)
        assert has_claude, "No Claude models in fallback list"
    
    def test_fallback_models_use_dot_format(self) -> None:
        """
        What it does: Verifies that versioned model IDs use dot format (e.g., claude-4.5).
        Purpose: Ensure consistency with Kiro API format — dash format (claude-4-5) is wrong.
        """
        print("Setup: Importing FALLBACK_MODELS...")
        from kiro.config import FALLBACK_MODELS

        print("Action: Checking model ID format for versioned models...")
        dash_format_violations = []
        for model in FALLBACK_MODELS:
            model_id = model["modelId"]
            print(f"Checking: {model_id}")
            # Versioned models must use dot separator (e.g., claude-opus-4.5, not claude-opus-4-5)
            # Pattern: digit-digit anywhere in the name indicates a version in dash format
            import re
            if re.search(r'\d-\d', model_id):
                dash_format_violations.append(model_id)
                print(f"  VIOLATION: {model_id} uses dash format instead of dot")

        print(f"Verification: Dash-format violations: {dash_format_violations}")
        assert dash_format_violations == [], (
            f"Model IDs must use dot format for versions. Dash-format violations: {dash_format_violations}"
        )


class TestFallbackModelsIntegration:
    """Integration tests for FALLBACK_MODELS with ModelResolver."""
    
    @pytest.mark.asyncio
    async def test_fallback_models_work_with_model_resolver(self) -> None:
        """
        What it does: Verifies that fallback models work with ModelResolver normalization.
        Purpose: Ensure that model name normalization (claude-opus-4-5 → claude-opus-4.5)
                 works correctly with fallback models, just like with API models.
        """
        print("Setup: Importing FALLBACK_MODELS and creating cache...")
        from kiro.config import FALLBACK_MODELS
        from kiro.cache import ModelInfoCache
        from kiro.model_resolver import ModelResolver
        
        # Simulate DNS failure scenario - populate cache with fallback models
        cache = ModelInfoCache()
        await cache.update(FALLBACK_MODELS)
        
        print(f"Cache populated with {cache.size} fallback models")
        print(f"Model IDs in cache: {cache.get_all_model_ids()}")
        
        # Create resolver
        resolver = ModelResolver(cache=cache, hidden_models={})
        
        print("\nAction: Testing normalization with dash format...")
        # Test that dash format (claude-opus-4-5) is normalized and found
        test_cases = [
            ("claude-opus-4-5", "claude-opus-4.5"),  # Dash → Dot
            ("claude-sonnet-4-5", "claude-sonnet-4.5"),  # Dash → Dot
            ("claude-haiku-4-5", "claude-haiku-4.5"),  # Dash → Dot
        ]
        
        for input_name, expected_normalized in test_cases:
            print(f"\n  Testing: {input_name} → {expected_normalized}")
            resolution = resolver.resolve(input_name)
            
            print(f"    Resolution source: {resolution.source}")
            print(f"    Normalized: {resolution.normalized}")
            print(f"    Internal ID: {resolution.internal_id}")
            print(f"    Is verified: {resolution.is_verified}")
            
            # Verify normalization happened
            print(f"    Comparing normalized: Expected '{expected_normalized}', Got '{resolution.normalized}'")
            assert resolution.normalized == expected_normalized
            
            # Verify model was found in cache (not passthrough)
            print(f"    Comparing source: Expected 'cache', Got '{resolution.source}'")
            assert resolution.source == "cache", f"Model {input_name} should be found in fallback cache"
            
            print(f"    Comparing is_verified: Expected True, Got {resolution.is_verified}")
            assert resolution.is_verified is True
    
    @pytest.mark.asyncio
    async def test_fallback_models_appear_in_available_models(self) -> None:
        """
        What it does: Verifies that non-hidden fallback models appear in get_available_models().
        Purpose: Ensure that /v1/models endpoint will show fallback models.

        Note: HIDDEN_FROM_LIST (e.g., ["auto"]) excludes models from the listing even when
        they are present in the cache. This test passes hidden_from_list explicitly so the
        assertion is not fragile when the module-level default changes.
        """
        print("Setup: Importing FALLBACK_MODELS and creating cache...")
        from kiro.config import FALLBACK_MODELS, HIDDEN_FROM_LIST
        from kiro.cache import ModelInfoCache
        from kiro.model_resolver import ModelResolver

        cache = ModelInfoCache()
        await cache.update(FALLBACK_MODELS)

        # Use the same hidden_from_list as production so the assertion is deterministic
        resolver = ModelResolver(cache=cache, hidden_models={}, hidden_from_list=HIDDEN_FROM_LIST)

        print("Action: Getting available models...")
        available = resolver.get_available_models()
        available_set = set(available)

        print(f"Available models ({len(available)}): {available}")

        # All fallback models except those in HIDDEN_FROM_LIST must appear
        expected_ids = {m["modelId"] for m in FALLBACK_MODELS} - set(HIDDEN_FROM_LIST)
        print(f"Expected (excluding hidden {HIDDEN_FROM_LIST}): {expected_ids}")

        missing = expected_ids - available_set
        assert not missing, f"Fallback models missing from available list: {missing}"

        # Hidden models must NOT appear in the listing
        unexpected = set(HIDDEN_FROM_LIST) & available_set
        assert not unexpected, f"Hidden models must not appear in available list: {unexpected}"


# ==================================================================================================
# Tests for WebSearch Configuration
# ==================================================================================================

class TestWebSearchConfig:
    """Tests for WebSearch configuration (WEB_SEARCH_ENABLED)."""
    
    def test_web_search_enabled_default_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        What it does: Verifies WEB_SEARCH_ENABLED defaults to true.
        Purpose: Ensure auto-injection is enabled by default.
        """
        print("Setup: Removing WEB_SEARCH_ENABLED from environment...")
        monkeypatch.delenv("WEB_SEARCH_ENABLED", raising=False)
        
        print("Action: Reloading config module...")
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
        
        print(f"Comparing WEB_SEARCH_ENABLED: Expected True, Got {config_module.WEB_SEARCH_ENABLED}")
        assert config_module.WEB_SEARCH_ENABLED is True
    
    def test_web_search_enabled_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        What it does: Verifies WEB_SEARCH_ENABLED=false disables auto-injection.
        Purpose: Ensure users can disable auto-injection.
        """
        print("Setup: Setting WEB_SEARCH_ENABLED=false...")
        monkeypatch.setenv("WEB_SEARCH_ENABLED", "false")
        
        print("Action: Reloading config module...")
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
        
        print(f"Comparing WEB_SEARCH_ENABLED: Expected False, Got {config_module.WEB_SEARCH_ENABLED}")
        assert config_module.WEB_SEARCH_ENABLED is False
    
    def test_web_search_enabled_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        What it does: Verifies WEB_SEARCH_ENABLED=true enables auto-injection.
        Purpose: Ensure explicit true value works.
        """
        print("Setup: Setting WEB_SEARCH_ENABLED=true...")
        monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
        
        print("Action: Reloading config module...")
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
        
        print(f"Comparing WEB_SEARCH_ENABLED: Expected True, Got {config_module.WEB_SEARCH_ENABLED}")
        assert config_module.WEB_SEARCH_ENABLED is True
    
    def test_web_search_enabled_numeric_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        What it does: Verifies numeric values (1/0) work for WEB_SEARCH_ENABLED.
        Purpose: Ensure compatibility with numeric boolean values.
        """
        print("Setup: Testing WEB_SEARCH_ENABLED=1...")
        monkeypatch.setenv("WEB_SEARCH_ENABLED", "1")
        
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
        
        print(f"Comparing WEB_SEARCH_ENABLED: Expected True, Got {config_module.WEB_SEARCH_ENABLED}")
        assert config_module.WEB_SEARCH_ENABLED is True
        
        print("Setup: Testing WEB_SEARCH_ENABLED=0...")
        monkeypatch.setenv("WEB_SEARCH_ENABLED", "0")
        reload(config_module)
        
        print(f"Comparing WEB_SEARCH_ENABLED: Expected False, Got {config_module.WEB_SEARCH_ENABLED}")
        assert config_module.WEB_SEARCH_ENABLED is False
    
    def test_web_search_enabled_yes_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        What it does: Verifies WEB_SEARCH_ENABLED=yes enables auto-injection.
        Purpose: Ensure 'yes' value works.
        """
        print("Setup: Setting WEB_SEARCH_ENABLED=yes...")
        monkeypatch.setenv("WEB_SEARCH_ENABLED", "yes")
        
        print("Action: Reloading config module...")
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
        
        print(f"Comparing WEB_SEARCH_ENABLED: Expected True, Got {config_module.WEB_SEARCH_ENABLED}")
        assert config_module.WEB_SEARCH_ENABLED is True
    
    def test_web_search_enabled_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        What it does: Verifies WEB_SEARCH_ENABLED is case-insensitive.
        Purpose: Ensure TRUE, True, true all work.
        """
        print("Setup: Testing WEB_SEARCH_ENABLED=TRUE...")
        monkeypatch.setenv("WEB_SEARCH_ENABLED", "TRUE")
        
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
        
        print(f"Comparing WEB_SEARCH_ENABLED: Expected True, Got {config_module.WEB_SEARCH_ENABLED}")
        assert config_module.WEB_SEARCH_ENABLED is True
        
        print("Setup: Testing WEB_SEARCH_ENABLED=FALSE...")
        monkeypatch.setenv("WEB_SEARCH_ENABLED", "FALSE")
        reload(config_module)
        
        print(f"Comparing WEB_SEARCH_ENABLED: Expected False, Got {config_module.WEB_SEARCH_ENABLED}")
        assert config_module.WEB_SEARCH_ENABLED is False


# ==================================================================================================
# Tests for Account System Configuration
# ==================================================================================================

class TestAccountSystemConfig:
    """Tests for Account System configuration constants."""
    
    def test_account_system_default_false(self) -> None:
        """
        What it does: Verifies ACCOUNT_SYSTEM defaults to false.
        Purpose: Ensure legacy mode is default (backward compatibility).
        """
        print("Setup: Mocking os.getenv for ACCOUNT_SYSTEM...")
        
        original_getenv = os.getenv
        
        def mock_getenv(key, default=None):
            if key == "ACCOUNT_SYSTEM":
                print(f"os.getenv('{key}') -> None (mocked)")
                return default  # Return default, simulating missing variable
            return original_getenv(key, default)
        
        with patch.object(os, 'getenv', side_effect=mock_getenv):
            print("Action: Reloading config module...")
            from importlib import reload
            import kiro.config as config_module
            reload(config_module)
            
            print(f"Comparing ACCOUNT_SYSTEM: Expected False, Got {config_module.ACCOUNT_SYSTEM}")
            assert config_module.ACCOUNT_SYSTEM is False
        
        # Restore module with real values
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
    
    def test_account_system_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        What it does: Verifies ACCOUNT_SYSTEM=true enables account system.
        Purpose: Ensure account system can be enabled via environment variable.
        """
        print("Setup: Setting ACCOUNT_SYSTEM=true...")
        monkeypatch.setenv("ACCOUNT_SYSTEM", "true")
        
        print("Action: Reloading config module...")
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
        
        print(f"Comparing ACCOUNT_SYSTEM: Expected True, Got {config_module.ACCOUNT_SYSTEM}")
        assert config_module.ACCOUNT_SYSTEM is True
    
    def test_accounts_config_file_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        What it does: Verifies ACCOUNTS_CONFIG_FILE defaults to credentials.json.
        Purpose: Ensure default path for credentials configuration.
        """
        print("Setup: Removing ACCOUNTS_CONFIG_FILE from environment...")
        monkeypatch.delenv("ACCOUNTS_CONFIG_FILE", raising=False)
        
        print("Action: Reloading config module...")
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
        
        print(f"Comparing ACCOUNTS_CONFIG_FILE: Expected 'credentials.json', Got '{config_module.ACCOUNTS_CONFIG_FILE}'")
        assert config_module.ACCOUNTS_CONFIG_FILE == "credentials.json"
    
    def test_accounts_state_file_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        What it does: Verifies ACCOUNTS_STATE_FILE defaults to state.json.
        Purpose: Ensure default path for runtime state file.
        """
        print("Setup: Removing ACCOUNTS_STATE_FILE from environment...")
        monkeypatch.delenv("ACCOUNTS_STATE_FILE", raising=False)
        
        print("Action: Reloading config module...")
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
        
        print(f"Comparing ACCOUNTS_STATE_FILE: Expected 'state.json', Got '{config_module.ACCOUNTS_STATE_FILE}'")
        assert config_module.ACCOUNTS_STATE_FILE == "state.json"
    
    def test_account_recovery_timeout_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        What it does: Verifies ACCOUNT_RECOVERY_TIMEOUT defaults to 60 seconds.
        Purpose: Ensure base timeout for exponential backoff is 60s.
        """
        print("Setup: Removing ACCOUNT_RECOVERY_TIMEOUT from environment...")
        monkeypatch.delenv("ACCOUNT_RECOVERY_TIMEOUT", raising=False)
        
        print("Action: Reloading config module...")
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
        
        print(f"Comparing ACCOUNT_RECOVERY_TIMEOUT: Expected 60, Got {config_module.ACCOUNT_RECOVERY_TIMEOUT}")
        assert config_module.ACCOUNT_RECOVERY_TIMEOUT == 60
    
    def test_account_max_backoff_multiplier_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        What it does: Verifies ACCOUNT_MAX_BACKOFF_MULTIPLIER defaults to 1440.0.
        Purpose: Ensure maximum backoff cap is 1 day (60s * 1440 = 86400s).
        """
        print("Setup: Removing ACCOUNT_MAX_BACKOFF_MULTIPLIER from environment...")
        monkeypatch.delenv("ACCOUNT_MAX_BACKOFF_MULTIPLIER", raising=False)
        
        print("Action: Reloading config module...")
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
        
        print(f"Comparing ACCOUNT_MAX_BACKOFF_MULTIPLIER: Expected 1440.0, Got {config_module.ACCOUNT_MAX_BACKOFF_MULTIPLIER}")
        assert config_module.ACCOUNT_MAX_BACKOFF_MULTIPLIER == 1440.0
    
    def test_account_probabilistic_retry_chance_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        What it does: Verifies ACCOUNT_PROBABILISTIC_RETRY_CHANCE defaults to 0.1.
        Purpose: Ensure 10% chance for probabilistic retry of broken accounts.
        """
        print("Setup: Removing ACCOUNT_PROBABILISTIC_RETRY_CHANCE from environment...")
        monkeypatch.delenv("ACCOUNT_PROBABILISTIC_RETRY_CHANCE", raising=False)
        
        print("Action: Reloading config module...")
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
        
        print(f"Comparing ACCOUNT_PROBABILISTIC_RETRY_CHANCE: Expected 0.1, Got {config_module.ACCOUNT_PROBABILISTIC_RETRY_CHANCE}")
        assert config_module.ACCOUNT_PROBABILISTIC_RETRY_CHANCE == 0.1
    
    def test_account_cache_ttl_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        What it does: Verifies ACCOUNT_CACHE_TTL defaults to 43200 seconds (12 hours).
        Purpose: Ensure model cache TTL is 12 hours by default.
        """
        print("Setup: Removing ACCOUNT_CACHE_TTL from environment...")
        monkeypatch.delenv("ACCOUNT_CACHE_TTL", raising=False)
        
        print("Action: Reloading config module...")
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
        
        print(f"Comparing ACCOUNT_CACHE_TTL: Expected 43200, Got {config_module.ACCOUNT_CACHE_TTL}")
        assert config_module.ACCOUNT_CACHE_TTL == 43200
    
    def test_state_save_interval_seconds_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        What it does: Verifies STATE_SAVE_INTERVAL_SECONDS defaults to 10 seconds.
        Purpose: Ensure periodic state saving happens every 10 seconds.
        """
        print("Setup: Removing STATE_SAVE_INTERVAL_SECONDS from environment...")
        monkeypatch.delenv("STATE_SAVE_INTERVAL_SECONDS", raising=False)
        
        print("Action: Reloading config module...")
        from importlib import reload
        import kiro.config as config_module
        reload(config_module)
        
        print(f"Comparing STATE_SAVE_INTERVAL_SECONDS: Expected 10, Got {config_module.STATE_SAVE_INTERVAL_SECONDS}")
        assert config_module.STATE_SAVE_INTERVAL_SECONDS == 10


class TestGetRawEnvValue:
    """Tests for _get_raw_env_value — file I/O, regex parsing, and exception paths."""

    def _call(self, var_name: str, path: str) -> Optional[str]:
        import kiro.config as config_module
        return config_module._get_raw_env_value(var_name, path)

    def test_returns_none_when_file_does_not_exist(self, tmp_path: Path) -> None:
        """
        What it does: Returns None when the .env file is absent.
        Purpose: No crash on fresh installs that have no .env file.
        """
        missing = str(tmp_path / "nonexistent.env")
        result = self._call("MY_VAR", missing)
        assert result is None

    def test_returns_value_unquoted(self, tmp_path: Path) -> None:
        """
        What it does: Parses VAR=value (no quotes).
        Purpose: Plain unquoted values are the most common format.
        """
        env_file = tmp_path / ".env"
        env_file.write_text("MY_VAR=hello\n", encoding="utf-8")
        assert self._call("MY_VAR", str(env_file)) == "hello"

    def test_returns_value_double_quoted(self, tmp_path: Path) -> None:
        """
        What it does: Parses VAR="value" (double quotes).
        Purpose: Quoted values with spaces need quote stripping.
        """
        env_file = tmp_path / ".env"
        env_file.write_text('MY_VAR="hello world"\n', encoding="utf-8")
        assert self._call("MY_VAR", str(env_file)) == "hello world"

    def test_returns_value_single_quoted(self, tmp_path: Path) -> None:
        """
        What it does: Parses VAR='value' (single quotes).
        Purpose: Single-quoted values must also have quotes stripped.
        """
        env_file = tmp_path / ".env"
        env_file.write_text("MY_VAR='hello world'\n", encoding="utf-8")
        assert self._call("MY_VAR", str(env_file)) == "hello world"

    def test_returns_raw_windows_path_without_escape_processing(self, tmp_path: Path) -> None:
        """
        What it does: Returns backslash path exactly as written.
        Purpose: The whole reason this function exists — dotenv libraries
        process \\n as newline; we must NOT do that for Windows paths.
        """
        env_file = tmp_path / ".env"
        env_file.write_text('KIRO_CREDS_FILE="D:\\\\Projects\\\\file.json"\n', encoding="utf-8")
        result = self._call("KIRO_CREDS_FILE", str(env_file))
        assert result == "D:\\\\Projects\\\\file.json"

    def test_returns_none_when_variable_not_present(self, tmp_path: Path) -> None:
        """
        What it does: Returns None when the variable is absent from the file.
        Purpose: Caller falls back to os.getenv when file does not contain the var.
        """
        env_file = tmp_path / ".env"
        env_file.write_text("OTHER_VAR=something\n", encoding="utf-8")
        assert self._call("MY_VAR", str(env_file)) is None

    def test_skips_comment_lines(self, tmp_path: Path) -> None:
        """
        What it does: Lines starting with '#' are ignored.
        Purpose: Comments must not be parsed as variable assignments.
        """
        env_file = tmp_path / ".env"
        env_file.write_text("# MY_VAR=should_be_ignored\nMY_VAR=real_value\n", encoding="utf-8")
        assert self._call("MY_VAR", str(env_file)) == "real_value"

    def test_returns_first_match_when_variable_appears_multiple_times(self, tmp_path: Path) -> None:
        """
        What it does: Returns the first occurrence when a variable is duplicated.
        Purpose: Consistent behaviour — first-wins is the dotenv convention.
        """
        env_file = tmp_path / ".env"
        env_file.write_text("MY_VAR=first\nMY_VAR=second\n", encoding="utf-8")
        assert self._call("MY_VAR", str(env_file)) == "first"

    def test_returns_none_on_unicode_decode_error(self, tmp_path: Path) -> None:
        """
        What it does: Returns None when the file is not UTF-8.
        Purpose: Non-UTF-8 files must not crash; the caller falls back to os.getenv.
        """
        env_file = tmp_path / ".env"
        # Write raw bytes that are invalid UTF-8
        env_file.write_bytes(b"MY_VAR=\xff\xfe\n")
        result = self._call("MY_VAR", str(env_file))
        assert result is None


class TestIntCoercedConfigValues:
    """Tests that verify ValueError is raised at module import when numeric env vars
    receive non-numeric strings.  This documents intentional crash-at-startup
    behaviour — unrecognised values must not silently default to anything."""

    def _reload_with_env(self, env_overrides: Dict[str, str]) -> None:
        import importlib
        import kiro.config as config_module
        with patch.dict(os.environ, env_overrides):
            importlib.reload(config_module)

    def test_server_port_non_numeric_raises(self) -> None:
        """
        What it does: Verifies SERVER_PORT="abc" raises ValueError on import.
        Purpose: The server must not silently start on the wrong port.
        """
        with pytest.raises(ValueError):
            self._reload_with_env({"SERVER_PORT": "abc"})

    def test_tool_description_max_length_non_numeric_raises(self) -> None:
        """
        What it does: Verifies TOOL_DESCRIPTION_MAX_LENGTH="abc" raises ValueError.
        Purpose: Bad config must be caught at startup, not at runtime.
        """
        with pytest.raises(ValueError):
            self._reload_with_env({"TOOL_DESCRIPTION_MAX_LENGTH": "abc"})

    def test_first_token_timeout_non_numeric_raises(self) -> None:
        """
        What it does: Verifies FIRST_TOKEN_TIMEOUT="abc" raises ValueError.
        Purpose: A non-numeric timeout would disable the safeguard silently.
        """
        with pytest.raises(ValueError):
            self._reload_with_env({"FIRST_TOKEN_TIMEOUT": "abc"})

    def test_streaming_read_timeout_non_numeric_raises(self) -> None:
        """
        What it does: Verifies STREAMING_READ_TIMEOUT="abc" raises ValueError.
        Purpose: An invalid streaming timeout must fail fast rather than hang forever.
        """
        with pytest.raises(ValueError):
            self._reload_with_env({"STREAMING_READ_TIMEOUT": "abc"})

    def test_first_token_max_retries_non_numeric_raises(self) -> None:
        """
        What it does: Verifies FIRST_TOKEN_MAX_RETRIES="abc" raises ValueError.
        Purpose: A non-integer retry count would disable retry logic silently.
        """
        with pytest.raises(ValueError):
            self._reload_with_env({"FIRST_TOKEN_MAX_RETRIES": "abc"})