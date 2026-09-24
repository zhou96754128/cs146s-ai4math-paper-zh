#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 PDF 的指定页渲染为 PNG（使用 macOS 自带 Quartz，无需第三方依赖）。
用法：/usr/bin/python3 render_page.py <pdf> <页码 1-based> <输出png> [缩放倍数]
"""
import sys

from Foundation import CFURLCreateFromFileSystemRepresentation
import Quartz


def main():
    src, page_no, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    scale = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0
    url = CFURLCreateFromFileSystemRepresentation(None, src.encode("utf-8"), len(src.encode("utf-8")), False)
    doc = Quartz.CGPDFDocumentCreateWithURL(url)
    if doc is None:
        raise SystemExit("cannot open pdf: %s" % src)
    page = Quartz.CGPDFDocumentGetPage(doc, page_no)
    if page is None:
        raise SystemExit("no such page: %d" % page_no)
    rect = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
    w, h = int(rect.size.width * scale), int(rect.size.height * scale)
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, 0, cs, Quartz.kCGImageAlphaPremultipliedFirst)
    Quartz.CGContextSetRGBFillColor(ctx, 1.0, 1.0, 1.0, 1.0)
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
    Quartz.CGContextScaleCTM(ctx, scale, scale)
    Quartz.CGContextDrawPDFPage(ctx, page)
    img = Quartz.CGBitmapContextCreateImage(ctx)
    outurl = CFURLCreateFromFileSystemRepresentation(None, out.encode("utf-8"), len(out.encode("utf-8")), False)
    dest = Quartz.CGImageDestinationCreateWithURL(outurl, "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dest, img, None)
    ok = Quartz.CGImageDestinationFinalize(dest)
    print("rendered p%d -> %s (%dx%d) ok=%s" % (page_no, out, w, h, ok))


if __name__ == "__main__":
    main()
