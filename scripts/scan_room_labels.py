"""Check the footprint of room labels near a raster floor plan's cropped edge."""
import io


def enclosed_bedrooms(image_bytes, labels):
    """Drop a neighboring room only when its body visibly continues past the sheet edge.

    A pair of nearby, same-height room captions straddling a continuous wall can be two
    legitimate rooms. Require the outer room's top and bottom lines to cross the page cut,
    no closing wall to that side, and another wall bounding the inner room.
    """
    if len(labels) < 2:
        return labels
    candidates = []
    for outside in labels:
        a = outside['box']
        for inside in labels:
            if outside is inside:
                continue
            b = inside['box']
            height = max(a[3]-a[1], b[3]-b[1])
            if abs(a[1]+a[3]-b[1]-b[3]) > .65*height:
                continue
            for flip in (False, True):
                left = 1000-a[2] if flip else a[0]
                outer_right = 1000-a[0] if flip else a[2]
                inner_left = 1000-b[2] if flip else b[0]
                gap = inner_left-outer_right
                if 0 < gap <= 2.2*height and left < 100 and inner_left < 160:
                    candidates.append((outside,inside,flip))
    if not candidates:
        return labels
    try:
        from PIL import Image
        with Image.open(io.BytesIO(image_bytes)) as im:
            gray = im.convert('L')
    except (ImportError, OSError, ValueError):
        return labels
    clipped = set()
    for outside,inside,flip in candidates:
        view = gray.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if flip else gray
        a,b = outside['box'],inside['box']
        w,h = view.size
        x0 = int((1000-a[2] if flip else a[0])*w/1000)
        x1 = int((1000-a[0] if flip else a[2])*w/1000)
        x2 = int((1000-b[2] if flip else b[0])*w/1000)
        x3 = int((1000-b[0] if flip else b[2])*w/1000)
        top, bottom = int(min(a[1],b[1])*h/1000), int(max(a[3],b[3])*h/1000)
        size = max(2,bottom-top)
        y0,y1 = max(0,top-3*size), min(h,bottom)
        if not 3 < x0 < x1 < x2 < x3 < w or y1-y0 < 2*size:
            continue
        px = view.load()
        def wall(x):
            return sum(px[x,y] < 165 for y in range(y0,y1)) >= .78*(y1-y0)
        if (not any(wall(x) for x in range(x1,x2)) or any(wall(x) for x in range(x0))
                or not any(wall(x) for x in range(x3,min(w,x3+int(.27*w))))):
            continue
        def reaches_edge(y):
            return px[0,y] < 165 and sum(px[x,y] < 165 for x in range(x0)) >= .80*x0
        if (any(reaches_edge(y) for y in range(max(0,top-15*size),top)) and
                any(reaches_edge(y) for y in range(bottom,min(h,bottom+12*size)))):
            clipped.add(id(outside))
    return [item for item in labels if id(item) not in clipped]
