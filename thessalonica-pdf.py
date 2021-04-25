#!/usr/bin/env python

# Copyright 2006 Google Inc. All Rights Reserved.
# Author: agl@imperialviolet.org (Adam Langley)
# Author: alexios@thessalonica.org.ru (Alexey Kryukov).
#
# Copyright (C) 2006 Google Inc.
# Copyright (C) 2009 alexios@thessalonica.org.ru (Alexey Kryukov).
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import re
import struct
import os
import zlib
#from PIL import Image

# This is a very simple script to make a PDF file out of the output of a
# multipage symbol compression.
# Run ./jbig2 -s -p <other options> image1.jpeg image1.jpeg ...
# python pdf.py [files to process] > out.pdf

# The following class is used to emulate variable assignment in
# conditions: while testing if a pattern corresponds to a specific
# regular expression we also preserve the 'match' object for future use.
class RegexpProcessor:
  def __init__( self, m=None ):
    self.m = m

  def test( self,pattern,string ):
    self.m = re.search( pattern,string )
    return not( self.m is None )

  def test_special( self,pattern,string,startpos=0 ):
    cp = re.compile( pattern )
    self.m = cp.search( string,startpos )
    return not( self.m is None )

  def match( self ):
    return self.m

class Ref:
  def __init__(self, x):
    self.x = x
  def __str__(self):
    return "%d 0 R" % self.x

class Dict:
  def __init__(self, values = {}):
    self.d = {}
    self.d.update(values)

  def __str__(self):
    s = ['<< ']
    for (x, y) in self.d.items():
      s.append('/%s ' % x)
      s.append(str(y))
      s.append("\n")
    s.append(">>\n")

    return ''.join(s)

  def __setitem__(self, key, value):
    self.d[key] = value

class Obj:
  next_id = 1
  def __init__(self, d = {}, stream = None):
    global global_next_id

    self.reinit(d, stream)
    self.id = global_next_id
    global_next_id += 1

  def __str__(self):
    s = []
    s.append(str(self.d))
    if self.stream is not None:
      s.append('stream\n')
      s.append(self.stream)
      s.append('\nendstream\n')
    s.append('endobj\n')

    return ''.join(s)

  def reinit(self, d = {}, stream = None):
    if stream is not None:
      d['Length'] = str(len(stream))
    self.d = Dict(d)
    self.stream = stream
  
  def addToDict(self, key, value):
    self.d[key] = value

class Doc:
  def __init__(self):
    self.objs = []
    self.pages = []

  def add_object(self, o):
    self.objs.append(o)
    return o

  def add_page(self, o):
    self.pages.append(o)
    return self.add_object(o)

  def __str__(self):
    a = []
    j = [0]
    offsets = []

    def add(x):
      a.append(x)
      j[0] += len(x) + 1
    add('%PDF-1.5')
    for o in self.objs:
      offsets.append(j[0])
      add('%d 0 obj' % o.id)
      add(str(o))
    xrefstart = j[0]
    a.append('xref')
    a.append('0 %d' % (len(offsets) + 1))
    a.append('0000000000 65535 f ')
    for o in offsets:
      a.append('%010d 00000 n ' % o)
    a.append('')
    a.append('trailer')
    a.append('<< /Size %d\n/Root 1 0 R >>' % (len(offsets) + 1))
    a.append('startxref')
    a.append(str(xrefstart))
    a.append('%%EOF')

    return '\n'.join(a)

def ref(x):
  return '%d 0 R' % x

def parse_palette(format, mode, spal):
  per_color  = len(mode)
  num_colors = len(spal) / per_color
  ret = []
  really_rgb = False
  
  for i in range(0, num_colors):
    # Modes except 'RGB' are untested. I am actually not sure PIL can ever generate
    # a palette with a colorspace different from RGB.
    if mode == "CMYK":
      color = (ord(spal[i*4]), ord(spal[i*4+1]), ord(spal[i*4+2]), ord(spal[i*4+3]))
    elif mode == "RGB":
      # An undocumented fact, probably a bug: PIL incorrectly orders palette colors
      # in indexed tiff files, first placing all red elements, then green and blue.
      # So here's a workaround.
      if format == 'tiff':
        color = (ord(spal[i]), ord(spal[i+num_colors]), ord(spal[i+num_colors*2]))
      else:
        color = (ord(spal[i*3]), ord(spal[i*3+1]), ord(spal[i*3+2]))

      # One more workaround: PIL always treats indexed images as if they had an RGB palette,
      # but it actually may well be in grayscale.
      if not really_rgb and (color[0] != color[1] or color[1] != color[2] or color[0] != color[2]):
        really_rgb = True
      
    elif per_color == 1:
      color = (ord(spal[i]))
    
    ret.append(color)
  
  if not really_rgb:
    for i in range(0, num_colors):
      ret[i] = (ret[i][0],)
    if len(ret) <= 2:
      mode = '1'
    else:
      mode = 'L'
  
  return(mode, tuple(ret))
    

def main(pagefiles):
  doc = Doc()
  doc.add_object(Obj({
    'Type' : '/Catalog',
    'Outlines' : ref(2),
    'Pages' : ref(3),
    'OCProperties' : '<< /OCGs[%s %s] /D<< /Intent /View /BaseState (ON) /Order[%s %s] >>>>' %
      (ref(5), ref(6), ref(5), ref(6))
    }))
  doc.add_object(Obj({
    'Type' : '/Outlines',
    'Count': '0'
    }))
  pages = Obj({
    'Type' : '/Pages'
    })
  doc.add_object(pages)
  creator = Obj({
    'Subtype' : '/Artwork',
    'Creator' : '(jbig2)',
    'Feature' : '(Layers)'
    })
  doc.add_object(creator)
  OCFore = Obj({
    'Type' : '/OCG',
    'Name' : '(Foreground)',
    'Usage' : "<</CreatorInfo %s>>" % ref(creator.id),
    'Intent' : '[/View/Design]'
    })
  doc.add_object(OCFore)
  OCBack = Obj({
    'Type' : '/OCG',
    'Name' : '(Background)',
    'Usage' : "<</CreatorInfo %s>>" % ref(creator.id),
    'Intent' : '[/View/Design]'
    })
  doc.add_object(OCBack)
  page_objs = []
  symd = None
  grexts = {
    'png' : 'png', 'PNG' : 'png',
    'jpg' : 'jpeg', 'JPG' : 'jpeg', 'jpeg' : 'jpeg', 'JPEG' : 'jpeg',
    'tif' : 'tiff', 'TIF' : 'tiff', 'tiff' : 'tiff', 'TIFF' : 'tiff'
    }
  cmodes = {
    'RGB' : '/DeviceRGB',
    'CMYK' : '/DeviceCMYK',
    'L' : '/DeviceGray',
    '1' : '/DeviceGray',
    'P' : '/Indexed'
  }

  for p in pagefiles:
    pname = p + '.jbig2'
    try:
      jbig2 = file(pname).read()
    except IOError:
      sys.stderr.write("error reading page file %s\n" % pname)
      continue
    (width, height) = struct.unpack('>II', jbig2[11:19])

    if os.access( p + ".sym", os.R_OK ):
      symd = doc.add_object(Obj({}, file(p + ".sym", 'rb').read()))
    if symd == None:
      sys.stderr.write("Could not find symbol dictionary %s.sym\n" % p)
      return
    
    xobj = Obj({
      'Type': '/XObject',
      'Subtype': '/Image',
      'OC' : ref(5),
      'Width': str(width),
      'Height': str(height),
      'ImageMask': 'true',
      'BitsPerComponent': '1',
      'Filter': '/JBIG2Decode',
      'DecodeParms': ' << /JBIG2Globals %d 0 R >>' % symd.id
      }, jbig2)
    contents = Obj({
      'Filter': '/FlateDecode'
      }, zlib.compress('q %d 0 0 %d 0 0 cm /Im1 Do Q' % (width, height)))
    resources = Obj({
      'ProcSet': '[/PDF /ImageB]',
      'XObject': '<< /Im1 %d 0 R >>' % xobj.id
      })
     
    bg_type = ''
    for ext in grexts.keys():
      if os.access(p + ".bg." + ext, os.R_OK):
        page_bg = p + ".bg." + ext
        bg_type = grexts[ext]
              
    
    if bg_type == 'jpeg':
      try:
        # Load the image into PIL just to get its size and other parameters
        im = Image.open(page_bg)
        (imw, imh) = im.size
        # But copy the image into pdf directly from the disk
        bgdata = file(page_bg).read()
      except IOError:
        sys.stderr.write("error reading background image %s\n" % page_bg)
        bg_type = ''

    elif bg_type == 'png' or bg_type == 'tiff':
      try:
        im = Image.open(page_bg)
        (imw, imh) = im.size
        bgdata = zlib.compress(im.tostring())
      except IOError:
        sys.stderr.write("error reading background image %s\n" % page_bg)
        bg_type = ''
    
    if bg_type != '':
        bgimage = Obj({
          'Type': '/XObject',
          'Subtype': '/Image',
          'OC' : ref(6),
          'Width':  str(imw),
          'Height': str(imh),
          }, bgdata)
        contents.reinit({
          'Filter': '/FlateDecode'
          }, zlib.compress('q %d 0 0 %d 0 0 cm /Im2 Do Q q %d 0 0 %d 0 0 cm /Im1 Do Q' %
            (width, height, width, height)))
        resources.reinit({
          'ProcSet': '[/PDF /ImageB]',
          'XObject': '<< /Im1 %d 0 R /Im2 %d 0 R >>' % (xobj.id, bgimage.id)
          })
        
        if not im.mode in cmodes.keys():
          im = im.convert('RGB')
        cspace = cmodes[im.mode]
        if cspace == '/Indexed':
          (mode, cpal) = parse_palette(bg_type, im.palette.mode, im.palette.tostring())
          cspace = "[" + cspace + " %s %d < " % (cmodes[mode], len(cpal) - 1)
          for color in cpal:
            for val in color:
              cspace = cspace + "%02x" % (val)
            cspace = cspace + " "
          cspace = cspace + ">]"

        bgimage.addToDict('ColorSpace', cspace)
        
        if im.mode == '1':
          bgimage.addToDict('BitsPerComponent', '1')
        else:
          bgimage.addToDict('BitsPerComponent', '8')
        
        if bg_type == 'jpeg':
          bgimage.addToDict('Filter', '/DCTDecode')
        elif bg_type == 'png' or bg_type == 'tiff':
          bgimage.addToDict('Filter', '/FlateDecode')
        
    doc_objs = [xobj, contents, resources]
    if bg_type != '':
      doc_objs.append(bgimage)

    page = Obj({
      'Type': '/Page',
      'Parent': '3 0 R',
      'MediaBox': '[ 0 0 %d %d ]' % (width, height),
      'Contents': ref(contents.id),
      'Resources': ref(resources.id)
      })

    doc_objs.append(page)
    [doc.add_object(x) for x in doc_objs]
    page_objs.append(page)

    pages.d.d['Count'] = str(len(page_objs))
    pages.d.d['Kids'] = '[' + ' '.join([ref(x.id) for x in page_objs]) + ']'
    
    sys.stderr.write("Processed %s\n" % pname)
    if bg_type != '':
      sys.stderr.write("Added background image from %s\n" % page_bg)

  print str(doc)

def usage(script, msg):
  if msg:
    sys.stderr.write("%s: %s\n"% (script, msg))
  sys.stderr.write("Usage: %s [files to process] > out.pdf\n"% script)
  sys.exit(1)
  
global_next_id = 1
proc = RegexpProcessor()

if __name__ == '__main__':
  if sys.platform == "win32":
    import msvcrt
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
  
  if len(sys.argv) > 1:
    files = sys.argv[1:]
  elif len(sys.argv) == 1:
    files = os.listdir(os.getcwd())
  else:
    usage(sys.argv[0], "wrong number of args!")

  pages = []
  for fname in files:
    if proc.test("(.*)\.jbig2", fname):
      pages.append(proc.match().group(1))

  if len(pages) == 0:
    usage(sys.argv[0], "no pages found!")
  
  main(pages)
  
