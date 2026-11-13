"""Necessary-condition gates for the benchmark's unmodified local_parse decision."""
import csv
import io
import itertools
import unittest

try:
    import numpy
    from PIL import Image
except ImportError:
    numpy = None


@unittest.skipUnless(numpy is not None, 'requires local Finnish runner dependencies')
class FinnishGateTests(unittest.TestCase):
    def test_vector_span_matches_original_green_bounds_including_exact_cutoff(self):
        from scripts import benchmark_cubicasa as bench, local_parse as engine
        image = Image.new('RGB', (30, 96), 'white')
        for x1, x2, color in [(8,10,(0,200,0)), (8,11,(0,200,0)), (8,22,(135,145,0)),
                               (8,22,(100,145,100)), (8,22,(100,146,100))]:
            sample = image.copy()
            sample.putpixel((x1, 64),color)
            sample.putpixel((x2, 64),color)
            original = any(engine.green_bounds(sample,y) is not None for y in range(image.height))
            self.assertEqual(bench.any_green_span(sample), original)

    def test_rejected_ocr_rows_cannot_produce_a_count_from_any_supported_label(self):
        from scripts import benchmark_cubicasa as bench, local_parse as engine
        image = Image.new('RGB', (100, 20), 'white')
        image.putpixel((20, 5), (0,200,0))
        image.putpixel((80, 5), (0,200,0))
        for x, word, eligible in [(20,'mh',True), (20,'moakuuh,',True), (80,'mh',False), (40,'WC',False)]:
            tsv = io.StringIO()
            writer = csv.writer(tsv, delimiter='\t')
            writer.writerow(('left', 'top', 'width', 'height', 'conf', 'text'))
            writer.writerow((x,0,8,10,85,word))
            self.assertEqual(bool(bench.viable_words(image,tsv.getvalue())),eligible)
            for n in range(1,len(engine.LABELS)+1):
                for labels in itertools.combinations(engine.LABELS,n):
                    status, _, _ = engine.link_regions(' '.join(labels), image, tsv.getvalue())
                    if status=='answered':
                        self.assertTrue(eligible)
