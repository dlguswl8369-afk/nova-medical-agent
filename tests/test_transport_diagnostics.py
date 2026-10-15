import io
import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'app')]
from public_samples import CountedClient
from nova_sdk import Client


class Response(io.BytesIO):
    status=200


class TransportDiagnosticTests(unittest.TestCase):
    def test_local_header_error_is_not_a_server_response(self):
        error=UnicodeEncodeError('latin-1','SYNTHETIC_PRIVATE_VALUE',0,1,'test')
        with patch.object(Client,'_open',side_effect=error):
            client=CountedClient('SYNTHETIC_NOT_A_KEY')
            with self.assertRaises(UnicodeEncodeError):client._request('GET','/v1/sample/cases')
        row=client.transport_diagnostics[0]
        self.assertTrue(row['connection_open_attempted'])
        self.assertFalse(row['http_response_received'])
        self.assertEqual(row['exception_type'],'UnicodeEncodeError')
        self.assertNotIn('SYNTHETIC_PRIVATE_VALUE',json.dumps(row))

    def test_listing_schema_without_patient_text(self):
        payload={'cases':[{'case_id':'00000000-0000-4000-8000-000000000001','initial':{'opening':'SYNTHETIC_PATIENT_TEXT'}}]}
        with patch.object(Client,'_open',return_value=Response(json.dumps(payload).encode())):
            client=CountedClient('SYNTHETIC_NOT_A_KEY');client._request('GET','/v1/sample/cases')
        row=client.transport_diagnostics[0]
        self.assertTrue(row['http_response_received']);self.assertTrue(row['sdk_response_received'])
        self.assertTrue(row['listing_schema']['every_entry_has_case_id'])
        self.assertNotIn('SYNTHETIC_PATIENT_TEXT',json.dumps(row))

    def test_session_confirmation_requires_valid_response(self):
        with patch.object(Client,'_open',return_value=Response(b'{"session_id":"00000000-0000-4000-8000-000000000002"}')):
            client=CountedClient('SYNTHETIC_NOT_A_KEY');client.create_sample('synthetic')
        self.assertEqual(client.confirmed_sample_sessions,1)
        self.assertTrue(client.transport_diagnostics[0]['valid_session_id_received'])
