import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'app')]
from public_samples import CountedClient,validate_development_key
from nova_sdk import Client,NovaError


class KeyInputTests(unittest.TestCase):
    def test_non_ascii_is_rejected_before_client_or_network(self):
        with patch.object(Client,'__init__') as init:
            with self.assertRaises(NovaError) as error:CountedClient('한글_합성_입력')
        self.assertEqual(error.exception.code,'LOCAL_KEY_NON_ASCII');init.assert_not_called()
        self.assertNotIn('한글',str(error.exception))

    def test_whitespace_and_controls_rejected(self):
        for token in [' SYNTHETIC','SYNTHETIC\n','SYNTHETIC\x00','SYN THETIC']:
            with self.assertRaises(NovaError) as error:validate_development_key(token)
            self.assertEqual(error.exception.code,'LOCAL_KEY_WHITESPACE_OR_CONTROL')

    def test_printable_token_unchanged_and_not_verified_as_credential(self):
        token='SYNTHETIC_NOT_A_KEY.123_-'
        self.assertIsNone(validate_development_key(token))
        self.assertEqual(CountedClient(token).token,token)

    def test_empty_rejected(self):
        with self.assertRaises(NovaError) as error:validate_development_key('')
        self.assertEqual(error.exception.code,'LOCAL_KEY_EMPTY')
