import unittest
from unittest.mock import Mock, MagicMock, patch
import os

from services.panel_tokens import encrypt_panel_password, decrypt_panel_password
from models.token_crypto import TokenEncryptionError


class TestPanelEncryption(unittest.TestCase):
    def setUp(self):
        self.old_key = os.environ.get("AGENT_TOKEN_ENCRYPTION_KEY")
        # Use a fixed valid Fernet key (32 bytes base64 encoded) for the tests
        os.environ["AGENT_TOKEN_ENCRYPTION_KEY"] = "UklmYm9oZ1lTZE5JUXBnTzVqV0dNZVh2aHNhdEp2bzc="

    def tearDown(self):
        if self.old_key is not None:
            os.environ["AGENT_TOKEN_ENCRYPTION_KEY"] = self.old_key
        else:
            os.environ.pop("AGENT_TOKEN_ENCRYPTION_KEY", None)

    def test_round_trip(self):
        password = "my_super_secret_password"
        ciphertext = encrypt_panel_password(password)
        self.assertNotEqual(password, ciphertext)
        self.assertTrue(ciphertext.startswith("gAAAAA"))
        
        decrypted = decrypt_panel_password(ciphertext)
        self.assertEqual(password, decrypted)

    def test_decrypt_invalid_ciphertext_raises_error(self):
        with self.assertRaises(TokenEncryptionError):
            decrypt_panel_password("invalid_ciphertext")

    @patch("scripts.migrate_panel_passwords.with_mysql_cursor")
    def test_migration_script(self, mock_cursor_ctx):
        from scripts.migrate_panel_passwords import migrate
        
        encrypted_pass = encrypt_panel_password("already_encrypted")
        
        # Mock cursor for select
        mock_select_cursor = Mock()
        mock_select_cursor.fetchall.return_value = [
            {"id": 1, "admin_password_encrypted": "plaintext_pass"},
            {"id": 2, "admin_password_encrypted": encrypted_pass},
        ]
        
        # Mock cursor for update
        mock_update_cursor = Mock()
        
        # Configure side_effect for with_mysql_cursor context manager calls.
        # Call 1 (dict_=True): yields mock_select_cursor
        # Call 2 (dict_=False): yields mock_update_cursor
        mock_cursor_ctx.side_effect = [
            MagicMock(**{"__enter__.return_value": mock_select_cursor}),
            MagicMock(**{"__enter__.return_value": mock_update_cursor}),
        ]
        
        migrate()
        
        # Check select query
        mock_select_cursor.execute.assert_called_once_with(
            "SELECT id, admin_password_encrypted FROM panels "
            "WHERE admin_password_encrypted IS NOT NULL AND admin_password_encrypted != ''"
        )
        
        # Check update query
        mock_update_cursor.execute.assert_called_once()
        update_args = mock_update_cursor.execute.call_args[0]
        self.assertIn("UPDATE panels SET admin_password_encrypted = %s WHERE id = %s", update_args[0])
        
        updated_val, updated_id = update_args[1]
        self.assertEqual(updated_id, 1)
        self.assertTrue(updated_val.startswith("gAAAAA"))
        self.assertEqual(decrypt_panel_password(updated_val), "plaintext_pass")
