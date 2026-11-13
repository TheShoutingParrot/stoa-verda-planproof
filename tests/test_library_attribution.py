from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from scripts.drawing_library import DrawingLibrary, PREFIX


class MemberAttributionTests(unittest.TestCase):
    def test_exact_member_credit_and_safe_link_with_untouched_original(self):
        rows = ('| example.ifc | KIT house | LicenseRef-KIT-unrestricted | IAI / KIT | https://example.org/kit |\n'
                '| other.ifc | Duplex | CC-BY-ND-3.0 | buildingSMART | javascript:alert(1) |\n'
                '| SAMPLE.ifc | Wrong filename | MIT | Other work | https://example.org/other |')
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'models.zip'
            with ZipFile(source, 'w') as z:
                for name in ('example.ifc', 'other.ifc', 'sample.ifc'):
                    z.writestr(PREFIX + 'data/ifc_models/' + name, b'raw\r\nbytes')
                z.writestr(PREFIX + 'data/ifc_models/LICENSE.md', rows)
            lib = DrawingLibrary(source)
            self.addCleanup(lib.close)
            directory = 'data/ifc_models/'
            example = lib.metadata(directory + 'example.ifc')
            self.assertEqual(example['attribution'], {'work':'KIT house', 'license':'LicenseRef-KIT-unrestricted',
                             'credit':'IAI / KIT', 'sourceUrl':'https://example.org/kit'})
            other = lib.details(directory + 'other.ifc')['drawing']['attribution']
            self.assertEqual(other['credit'], 'buildingSMART')
            self.assertIsNone(other['sourceUrl'])
            self.assertNotIn('attribution', lib.metadata(directory + 'sample.ifc'))
            self.assertEqual(lib.read_bytes(directory + 'other.ifc'), b'raw\r\nbytes')
