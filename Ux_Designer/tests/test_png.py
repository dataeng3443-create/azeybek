from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from PIL import Image
import reference as creative


class ReferencePngTests(unittest.TestCase):
    def test_standard_modes_and_transparency(self):
        with tempfile.TemporaryDirectory() as folder:
            for mode in ('1', 'L', 'LA', 'P', 'RGB', 'RGBA', 'I;16'):
                with self.subTest(mode=mode):
                    path = Path(folder) / 'sample.png'
                    image = Image.new(mode, (48, 24))
                    image.save(path)
                    before = path.read_bytes()
                    result = creative.reference_profile(path)
                    self.assertEqual((result['width'], result['height']), (48, 24))
                    self.assertEqual(path.read_bytes(), before)

    def test_palette_colors_match_rgb(self):
        with tempfile.TemporaryDirectory() as folder:
            rgb = Image.new('RGB', (40, 20), (20, 160, 110))
            for mode, image in [('RGB', rgb), ('P', rgb.quantize(colors=2))]:
                path = Path(folder) / (mode + '.png')
                image.save(path)
                self.assertEqual(creative.reference_profile(path)['palette'], 'teal')

    def test_corrupt_and_non_png_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.png'
            Image.new('RGB', (12, 12)).save(path, format='JPEG')
            with self.assertRaises(ValueError): creative.reference_profile(path)
            Image.new('RGB', (12, 12)).save(path)
            path.write_bytes(path.read_bytes()[:40])
            with self.assertRaises(ValueError): creative.reference_profile(path)

    def test_adam7_and_16_bit_rgb(self):
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        with tempfile.TemporaryDirectory() as folder:
            for bits, interlaced in [(8, 1), (16, 0)]:
                # Uniform 8x8 RGB fixture, encoded with all seven Adam7 passes.
                pixel = bytes([20, 160, 110]) if bits == 8 else struct.pack('>HHH', 20*257, 160*257, 110*257)
                passes = [(0,0,8,8),(4,0,8,8),(0,4,4,8),(2,0,4,4),(0,2,2,4),(1,0,2,2),(0,1,1,2)] if interlaced else [(0,0,1,1)]
                data = b''.join((b'\x00' + pixel * len(range(x,8,dx))) * len(range(y,8,dy)) for x,y,dx,dy in passes)
                png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB',8,8,bits,2,0,0,interlaced)) + chunk(b'IDAT',zlib.compress(data)) + chunk(b'IEND',b'')
                path = Path(folder) / 'fixture.png'; path.write_bytes(png)
                self.assertEqual(creative.reference_profile(path)['palette'], 'teal')

    def test_transparent_pixels_do_not_select_accent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'alpha.png'
            Image.new('RGBA', (20, 20), (20,160,110,0)).save(path)
            self.assertEqual(creative.reference_profile(path)['palette'], 'cobalt')


if __name__ == '__main__': unittest.main()
