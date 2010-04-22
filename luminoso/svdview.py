import sys
import re
from PyQt4.QtCore import Qt, QRectF as Rect, QPointF as Point, QLineF as Line, QSize, QMutex, QObject, QString, QTimer, SIGNAL
from PyQt4.QtGui import QApplication, QColor, QWidget, QImage, QPainter, QPen, QFont, QFontMetrics, QVBoxLayout, QComboBox, QLabel, QPushButton, QGridLayout, QCompleter
import numpy as np
from csc.util.persist import get_picklecached_thing
from csc.divisi.tensor import data
from collections import defaultdict

# This initializes Qt, and nothing works without it. Even though we
# don't use the "app" variable until the end.
if __name__ == '__main__':
    app = QApplication(sys.argv)

#defaultFont = QFont()

# Setting up the similarity colors
simcolors = np.zeros((600, 3))

# dark gray to red
simcolors[:200, 0] = np.arange(30, 230)
simcolors[:200, 1:] = 30

# red to yellow
simcolors[200:400, 0] = 230
simcolors[200:400, 1] = np.arange(30, 230)
simcolors[200:400, 2] = 30

# yellow to white
simcolors[400:600, :2] = 230
simcolors[400:600, 2] = np.arange(30, 230)

FLIP_Y = np.int32([1, -1])
TIMER_MAX = 50

# The modifier that, if held while pressing the left mouse button,
# fakes a right mouse click. "Meta" = Control on Mac, Logo on Windows.
RIGHT_BUTTON_MODIFIER = Qt.MetaModifier

class Projection(QObject):
    """
    Represents a projection from K dimensions into 2 dimensions.
    
    The input space is called the "component space", and the output
    space is called the "projection plane", representing projection
    coordinates.
    """
    def __init__(self, k):
        QObject.__init__(self)
        self.k = k
        self.matrix = np.zeros((k, 2))
        self.target_matrix = np.zeros((k, 2))
        self.reset_projection()
        self.mouse_rotation = False

    def reset_projection(self):
        self.target_matrix[:] = 0
        for idx in (0, 1):
            self.target_matrix[idx, idx] = 1
        self.emit(SIGNAL('reset()'))

    def components_to_projection(self, vec):
        try:
            return np.dot(vec, self.matrix[:, :vec.shape[-1]])
        except ValueError:
            raise ValueError("Couldn't calculate dot product of %r (shape=%r, k=%d)" % (vec, vec.shape, self.k))
    
    def components_to_target(self, vec):
        try:
            return np.dot(vec, self.target_matrix[:, :vec.shape[-1]])
        except ValueError:
            raise ValueError("Couldn't calculate dot product of %r (shape=%r, k=%d)" % (vec, vec.shape, self.k))
    
    def orthogonalize(self, power=1.0):
        """
        Use normalization and Gram-Schmidt orthogonalization to ensure that
        this projection represents a valid rotation of the component space,
        not a dilation or skew.

        Actually, now it only does that when power=1. When power is less, the
        space will not enforce strict rotations, it will only make the space
        wobble back toward orthogonality.
        """
        prev = self.target_matrix.copy()
        self.target_matrix[:,0] /= np.linalg.norm(self.target_matrix[:,0])
        self.target_matrix[:,1] -= self.target_matrix[:,0] * np.dot(self.target_matrix[:,0], self.matrix[:,1])
        self.target_matrix[:,1] /= np.linalg.norm(self.target_matrix[:,1])
        self.target_matrix[:,:] = self.target_matrix*(power) + prev*(1-power)
        if np.any(np.isnan(self.target_matrix)):
            # "rollback" to a projection we know was valid
            print 'rollback'
            self.target_matrix = prev

    def move_towards(self, vec, target):
        orig = self.components_to_target(vec)
        delta = (target - orig) / np.dot(vec, vec)
        self.target_matrix += delta[np.newaxis,:] * vec[:,np.newaxis]
        magnitude = np.sum(delta**2)
        power = np.tanh(magnitude)/10
        self.orthogonalize(power=power)
        self.emit(SIGNAL('rotated()'))

    def timerEvent(self):
        """
        Move the current projection halfway toward the desired one.
        """
        self.matrix = (self.matrix * .5) + (self.target_matrix * .5)

    def set_x_axis(self, vec):
        self.target_matrix[:,0] = vec / np.linalg.norm(vec)
        self.target_matrix[:,1] -= self.component(self.target_matrix[:,1],vec)
    
    def set_y_axis(self, vec):
        self.target_matrix[:,1] = vec / np.linalg.norm(vec)
        self.target_matrix[:,0] -= self.component(self.target_matrix[:,0],vec)

    def component(self, vec, reference):
        "Return the component of a vector in the direction of another vector."
        reference_norm = reference / np.linalg.norm(reference)
        return reference_norm * np.dot(vec, reference_norm)

    def next_axis(self):
        self.target_matrix = np.concatenate(
            [self.target_matrix[-1:], self.target_matrix[:-1]],
            axis=0)
        self.emit(SIGNAL('rotated()'))
    def prev_axis(self):
        self.target_matrix = np.concatenate(
            [self.target_matrix[1:], self.target_matrix[:1]],
            axis=0)
        self.emit(SIGNAL('rotated()'))

class Layer(object):
    """
    An abstract class representing a layer of information that can be drawn
    on a SVDViewer.
    """
    def __init__(self, luminoso):
        """
        Create a Layer on a certain Luminoso viewer.

        Specific Layers can also take additional arguments and do additional
        things in their initializers. They still must take the viewer as
        their first argument (and preferably should delegate to Layer to
        set self.luminoso).
        """
        self.luminoso = luminoso

    def draw(self, painter):
        """
        Whenever the Layer needs to redraw itself, this function will be
        called, and passed a QtPainter object as an argument, which the Layer
        can use to put the appropriate graphics on the screen.
        """
        pass

    def resize(self, width, height):
        """
        This function is called to inform a Layer that it is being resized,
        with the new width and height in pixels as arguments. The default
        behavior is to do nothing.
        """
        pass

    def mouseMoveEvent(self, event):
        """
        Informs a Layer that the mouse has moved. The default behavior is to
        do nothing.
        """
        pass

    def mousePressEvent(self, event):
        """
        Informs a Layer that the mouse has been clicked. The default behavior
        is to do nothing.

        Which buttons are being pressed can be checked with an operation
        such as `event.buttons() & Qt.LeftButton`.
        """
        pass
    
    def mouseReleaseEvent(self, event):
        """
        Informs a Layer that a mouse button has been released. The default
        behavior is to do nothing.
        """
        pass

    def wheelEvent(self, event):
        """
        Informs a Layer that the mouse wheel has moved. The default behavior
        is to do nothing.
        """
        pass

    def selectEvent(self, index):
        """
        Triggered when a new Concept is selected. The argument is the index
        in Luminoso's lists representing that concept.
        """
        pass

    def timerEvent(self):
        """
        Triggered at regular intervals, up to 20 times per second.
        """
        pass
    
class PixelRenderingLayer(Layer):
    """
    A layer representing the data in an SVD with fast pixel operations.
    This layer should be drawn first, and then additional data can be drawn
    over it.
    """
    def __init__(self, luminoso):
        """
        Calls resize() to set up a pixmap of the correct size.
        """
        Layer.__init__(self, luminoso)
        self.resize(self.luminoso.width, self.luminoso.height)

    def resize(self, width, height):
        """
        When this layer is created or resized, create a pixmap the size of
        the layer, which is drawn as a QImage. We can later twiddle
        self.pixels and have the results appear in the image.
        """
        self.pixels = np.zeros((height, width, 4), dtype='uint8')
        self.img = QImage(self.pixels, width, height, QImage.Format_RGB32)

    def draw(self, painter):
        pixels = self.pixels

        # Get the center pixel we should set for each point in the SVD
        # space. Points outside of the current window will be drawn at
        # the edges and then covered up.
        screenpts = self.luminoso.constrain_to_screen(self.luminoso.screenpts)

        colors = self.luminoso.colors[:, ::-1]

        # Draw a +-shaped point for every point in the space.
        pixels[:, :, :3] = 0
        pixels[:, :, 3] = 255
        pixels[screenpts[1]+1, screenpts[0], :3] = colors*0.5
        pixels[screenpts[1]-1, screenpts[0], :3] = colors*0.5
        pixels[screenpts[1], screenpts[0]+1, :3] = colors*0.5
        pixels[screenpts[1], screenpts[0]-1, :3] = colors*0.5
        pixels[screenpts[1], screenpts[0], :3] = colors

        # Put a 3-pixel border on the screen to cover the "offscreen"
        # points. Yes, it's cheap.
        pixels[:3, :, :3] = 100
        pixels[-3:, :, :3] = 100
        pixels[:, :3, :3] = 100
        pixels[:, -3:, :3] = 100

        painter.drawImage(0, 0, self.img)

def quadrange(maximum, steps):
    """
    This nifty little function generates a sequence of `steps` distinct
    integers, starting from 0, with the average step size increasing
    linearly until just before the sequence reaches `maximum`. The result is
    a sequence that grows quadratically over your range of numbers, emphasizing
    the low numbers in the range.

    This is used in the labeling procedure, to focus on labeling points that
    are closer to the mouse pointer.

    Example:

        >>> quadrange(1000, 10)
        array([  0,  10,  41,  92, 162, 252, 362, 492, 641, 810])

    If `steps` is greater than `maximum`, it returns just the range up to
    `maximum`.

        >>> quadrange(10, 1000)
        array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    """
    if steps >= maximum: return np.arange(maximum)
    return np.int32(np.linspace(0, np.sqrt(maximum-steps), steps, endpoint=False) ** 2) + np.arange(steps)

class PointLayer(Layer):
    """
    A layer that draws points of different sizes based on their overall
    magnitude (leaving some points undrawn).
    """
    def __init__(self, luminoso, npoints=1000):
        Layer.__init__(self, luminoso)
        self.npoints = npoints
        self.calculate_magnitudes()

    def draw(self, painter):
        painter.setPen(Qt.NoPen)
        
        whichpoints = self.luminoso.is_point_on_screen(self.luminoso.screenpts)
        pointlist = np.flatnonzero(whichpoints)
        
        subsizes = self.sizes[pointlist]
        sub_order = np.argsort(-subsizes)
        order = pointlist[sub_order]
        pixelsize = self.luminoso.pixel_size()

        # draw the origin
        if self.luminoso.is_point_on_screen(np.zeros((2,))):
            x, y = self.luminoso.projection_to_screen(np.zeros((2,)))
            painter.setBrush(QColor(100, 100, 100))
            painter.drawEllipse(Point(x, y), 6, 6)
            painter.setBrush(QColor(255, 255, 255))
            painter.drawEllipse(Point(x, y), 2, 2)
        for i in xrange(min(len(order), self.npoints)):
            coords = self.luminoso.screenpts[order[i]]
            x, y = coords
            r, g, b = self.luminoso.colors[order[i]]
            if i <= 1:
                b = g = r = 230
            size = self.sizes[order[i]] / pixelsize
            if size >= 1 and self.luminoso.is_on_screen(x, y):
                painter.setBrush(QColor(r, g, b))
                painter.drawEllipse(Point(x, y), size, size)
    
    def calculate_magnitudes(self):
        """
        Assign every point a size according to its distance from the origin.
        """
        self.sizes = np.sum(self.luminoso.array ** 2, axis=-1) ** 0.25
        self.sizes /= (np.sum(self.sizes) / len(self.sizes))
        self.sizes *= self.luminoso.scale / 10000

class LabelLayer(Layer):
    """
    A layer for labeling points in an SVD.
    """
    def __init__(self, luminoso, nlabels=400, npoints=1000):
        Layer.__init__(self, luminoso)
        self.nlabels = nlabels
        self.npoints = npoints
        self.whichlabels = quadrange(self.luminoso.npoints, npoints)
        self.update_order()

    def draw(self, painter):
        labeled_so_far = 0
        self.label_mask[:] = False
        label_indices = [self.luminoso.selected_index] + [self.order[i] for i in self.whichlabels]
        for (i, lindex) in enumerate(label_indices):
            if lindex is None: continue
            x, y = self.luminoso.screenpts[lindex]
            if not self.luminoso.is_on_screen(x, y) or self.label_mask[x, y]:
                continue

            r, g, b = self.luminoso.colors[lindex] + 25
            # Make currently selected point white.
            if i == 0: b = g = r = 255

            text = self.luminoso.labels[lindex]
            if text is None: continue

            # Mask out areas that already have label text.
            dist = self.distances[lindex]
            width = int(dist/2) + 16
            height = int(dist/8) + 4
            xmin = max(x-width, 0)
            xmax = min(x+width, self.luminoso.width)
            ymin = max(y-height, 0)
            ymax = min(y+height, self.luminoso.height)
            self.label_mask[xmin:xmax, ymin:ymax] = True

            painter.setPen(QColor(0, 0, 0))
            painter.drawText(Point(x+5, y+5), unicode(text))
            painter.setPen(QColor(r, g, b))
            painter.drawText(Point(x+4, y+4), unicode(text))

            labeled_so_far += 1
            if labeled_so_far >= self.nlabels: break

    def wheelEvent(self, event):
        self.update_order()

    def mouseMoveEvent(self, event):
        self.update_order()

    def resize(self, width, height):
        self.label_mask = np.zeros((self.luminoso.width, self.luminoso.height), dtype=np.bool8)
        
    def update_order(self):
        self.distances = self.luminoso.distances_from_mouse(self.luminoso.array)
        self.order = np.argsort(self.distances)

class SelectionLayer(Layer):
    """
    A layer that sets and displays the current selection.
    """
    def draw(self, painter):
        if self.luminoso.selected_index is not None:
            painter.setPen(QColor(255, 255, 255))
            painter.setBrush(QColor(255, 255, 0))
            vec = self.luminoso.selected_vector()
            text = self.luminoso.selected_label()

            if text is None:
                # The selection was deleted in real-time data. Bail out.
                return

            x, y = self.luminoso.components_to_screen(vec)
            painter.drawEllipse(Point(x, y), 3, 3)
            painter.setPen(Qt.NoPen)
            painter.drawText(Point(x+4, y+4), unicode(text))

    def mousePressEvent(self, event):
        if self.luminoso.leftMouseDown():
            self.luminoso.select_nearest_point()

class SimilarityLayer(Layer):
    def selectEvent(self, index):
        vec = self.luminoso.array[index]
        sim = np.dot(self.luminoso.array, vec) / np.linalg.norm(vec) / np.sqrt(np.sum(self.luminoso.array ** 2, axis=1))
        sim_indices = np.clip(np.int32(sim*600 + 300), 0, 599)
        self.luminoso.colors = simcolors[sim_indices]

    def mouseReleaseEvent(self, event):
        self.luminoso.update_colors()

class RotationLayer(Layer):
    def draw(self, painter):
        pass

    def timerEvent(self):
        proj = self.luminoso.projection
        if self.luminoso.leftMouseDown() and self.luminoso.selected_index is not None:
            self.luminoso.setCursor(Qt.ClosedHandCursor)
            x = self.luminoso.mouseX
            y = self.luminoso.mouseY
            proj.move_towards(self.luminoso.selected_vector(),
                self.luminoso.screen_to_projection(np.array([x, y])))

    def mouseReleaseEvent(self, event):
        self.luminoso.setCursor(Qt.ArrowCursor)    

class PanZoomLayer(Layer):
    def __init__(self, luminoso):
        Layer.__init__(self, luminoso)
        self.panPt = None

    def draw(self, painter):
        pass
        
    def wheelEvent(self, event):
        magnitude = .9995 ** event.delta()
        oldPt = self.luminoso.screen_to_projection(np.array([event.pos().x(), event.pos().y()]))
        self.luminoso.screen_size *= magnitude
        newPt = self.luminoso.screen_to_projection(np.array([event.pos().x(), event.pos().y()]))
        self.luminoso.screen_center += (oldPt - newPt)
    
    def mousePressEvent(self, event):
        if event.buttons():
            self.panPt = self.luminoso.screen_to_projection(np.array([event.pos().x(), event.pos().y()]))

    def mouseMoveEvent(self, event):
        if self.panPt is not None and self.luminoso.rightMouseDown():
            self.luminoso.setCursor(Qt.ClosedHandCursor)
            newPt = self.luminoso.screen_to_projection(np.array([event.pos().x(), event.pos().y()]))
            delta = newPt - self.panPt
            self.luminoso.screen_center -= delta

    def mouseReleaseEvent(self, event):
        self.luminoso.setCursor(Qt.ArrowCursor)    

class CanonicalLayer(Layer):
    def __init__(self, luminoso, canonical):
        Layer.__init__(self, luminoso)
        self.canonical = canonical
    def draw(self, painter):
        origin = np.zeros((2,))
        origin_pt = Point(*self.luminoso.projection_to_screen(origin))
        #painter.setCompositionMode(QPainter.CompositionMode_Screen)
        for axis in xrange(self.luminoso.k):
            projpoint = self.luminoso.projection.matrix[axis]/2
            x, y = self.luminoso.projection_to_screen(projpoint)
            target_pt = Point(x, y)
            painter.setPen(QColor(100, 100, 100))
            painter.drawLine(Line(origin_pt, target_pt))
            painter.setPen(QColor(180, 180, 180))
            painter.drawText(Point(x+2, y+2), str(axis))

        painter.setPen(QColor(200, 200, 0))
        for canon in self.canonical:
            index = self.luminoso.labels.index(canon)
            components = self.luminoso.array[index]
            target_pt = Point(*self.luminoso.components_to_screen(components))
            # draw a yellowish line from the origin to the canonical doc
            painter.drawLine(Line(origin_pt, target_pt))
        #painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

class LinkLayer(Layer):
    def __init__(self, luminoso, matrix):
        Layer.__init__(self, luminoso)
        self.matrix = matrix
        
        self.source = None
        # poke the matrix to make sure it's loaded
        self.matrix[self.matrix.labels((0, 0))]
        self.connections = []

    def selectEvent(self, selected_index):
        selectkey = self.luminoso.labels[selected_index]
        connections = []
        if selectkey in self.matrix.label_list(0):
            for (other,) in self.matrix[selectkey,:]:
                try:
                    index = self.luminoso.labels.index(other)
                    connections.append(index)
                except KeyError:
                    pass
        if selectkey in self.matrix.label_list(1):
            for (other,) in self.matrix[:,selectkey].keys():
                try:
                    index = self.luminoso.labels.index(other)
                    connections.append(index)
                except KeyError:
                    pass
        
        self.source = selected_index
        self.connections = connections
    
    def draw(self, painter):
        if self.source:
            source_pt = Point(*self.luminoso.components_to_screen(self.luminoso.array[self.source]))
            target_pts = [Point(*p) for p in self.luminoso.components_to_screen(self.luminoso.array[self.connections])]
            lines = [Line(source_pt, target_pt) for target_pt in target_pts]

            painter.setPen(QColor(0, 100, 200, 120))
            #painter.setCompositionMode(QPainter.CompositionMode_Screen)
            painter.drawLines(lines)
            #painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        
class SVDViewer(QWidget):
    def __init__(self, array, labels, **options):
        QWidget.__init__(self)
        assert isinstance(array, np.ndarray),\
                "Got a %s instead of an ndarray" % type(array)
        # figure out our size
        self.width = self.size().width()
        self.height = self.size().height()

        self.labels = labels
        self.array = array
        self.orig_array = self.array.copy()

        self.npoints = self.array.shape[0]
        self.scale = self.calculate_scale()
        if options.get('jitter', True):
            self.add_jitter()

        self.layers = []
        self.k = self.array.shape[1]

        self.projection = Projection(self.k)

        # create our internal display
        self.painter = QPainter()

        self.selected_index = None
        self.mouseX = 0
        self.mouseY = 0
        self.buttons = 0
        
        # avoid racing
        self.paint_lock = QMutex()
        self.timer = QTimer(self)
        self.timer_ticks = 0
        self.timer.setInterval(30)
        self.connect(self.timer, SIGNAL('timeout()'), self.timerEvent)
        self.timer.start()

        self.setMouseTracking(True)
        self.default_colors = self.components_to_colors(self.array)[:]
        self.update_colors()

        # initialize the mapping from projection coordinates to screen
        # coordinates
        self.reset_view()
    
    def age_timer(self):
        self.timer_ticks += 1
        if self.timer_ticks == TIMER_MAX:
            self.timer.stop()

    def activate_timer(self):
        if self.timer_ticks >= TIMER_MAX:
            self.timer.start()
        self.timer_ticks = 0

    def stop_timer(self):
        self.timer.stop()

    def __del__(self):
        self.stop_timer()

    def calculate_scale(self):
        """
        Find roughly the median of axis coordinates, determining
        a reasonable zoom level for the initial view. Make sure it's non-zero.
        """
        coords = [c for c in np.abs(self.array.flatten()) if c > 0] + [1.0]
        coords.sort()
        return coords[len(coords)//2]
    
    def add_jitter(self):
        self.jitter = np.exp(np.random.normal(size=self.array.shape) / 50.0)
        self.array *= self.jitter

    def insert_layer(self, pos, layertype, *args):
        """
        Add a layer of visualization to this widget, by specifying the
        subclass of Layer and whatever arguments its constructor takes.
        """
        self.layers.insert(pos, layertype(self, *args))
    
    def add_layer(self, layertype, *args):
        """
        Add a layer of visualization to this widget, by specifying the
        subclass of Layer and whatever arguments its constructor takes.
        """
        self.layers.append(layertype(self, *args))
    
    def reset_view(self):
        self.screen_center = np.array([0., 0.])
        self.screen_size = np.array([self.scale/2, self.scale/2])
        self.projection.reset_projection()
        self.set_default_axes()
        self.update_screenpts()
        self.update()

    @staticmethod
    def make_svdview(tensor, svdtensor, canonical=None):
        widget = SVDViewer(data(svdtensor), svdtensor.label_list(0))
        widget.setup_standard_layers()
        widget.set_default_axes()
        if canonical is None: canonical = []
        widget.insert_layer(1, CanonicalLayer, canonical)
        widget.insert_layer(2, LinkLayer, tensor.bake())
        return widget

    @staticmethod
    def make_colors(tensor, svdtensor):
        widget = SVDViewer(data(svdtensor), svdtensor.label_list(0))
        widget.setup_standard_layers()
        
        from csc.concepttools.colors import text_color
        colors = [text_color(text) for text in widget.labels]
        widget.default_colors = np.clip(np.array(colors), 55, 230)
        widget.update_colors()
        return widget

    @staticmethod
    def make(array, labels):
        widget = SVDViewer(array, labels)
        widget.setup_standard_layers()
        return widget
    
    def setup_standard_layers(self):
        self.add_layer(PixelRenderingLayer)
        self.add_layer(PointLayer)
        self.add_layer(LabelLayer)
        self.add_layer(SelectionLayer)
        self.add_layer(SimilarityLayer)
        self.add_layer(RotationLayer)
        self.add_layer(PanZoomLayer)
    
    def set_default_axes(self):
        self.set_axis_to_text(0, 'DefaultXAxis')
        self.set_axis_to_text(1, 'DefaultYAxis')
    
    def set_default_x_axis(self):
        self.set_axis_to_text(0, 'DefaultXAxis')

    def set_default_y_axis(self):
        self.set_axis_to_text(1, 'DefaultYAxis')

    def set_axis_to_pc(self, axis, pc):
        """
        Sets an axis to a particular principal component.
        """
        pcvec = np.zeros((self.array.shape[1],))
        pcvec[pc] = 1.0

        if axis == 0:
            self.projection.set_x_axis(pcvec)
        elif axis == 1:
            self.projection.set_y_axis(pcvec)
        self.activate_timer()

    def set_axis_to_text(self, axis, text):
        if isinstance(text, QString):
            text = unicode(text)
        if not text: return
        if text in self.labels:
            index = self.labels.index(text)
            if axis == 0:
                self.projection.set_x_axis(self.array[index,:])
            elif axis == 1:
                self.projection.set_y_axis(self.array[index,:])
            self.activate_timer()
        else:
            print repr(text), "not in label list"

    def is_point_on_screen(self, coords):
        return np.all((coords >= np.int32([0, 0])) &
                      (coords < np.int32([self.width, self.height])),
                      axis=-1)
    
    def is_on_screen(self, x, y):
        return x >= 0 and x < self.width and y >= 0 and y < self.height

    def pixel_size(self):
        """
        What is the diameter of a single pixel at the current zoom level?
        
        If the x and y scales end up being different, take the geometric mean.
        """
        xsize = self.screen_size[0] / self.width
        ysize = self.screen_size[1] / self.height
        return np.sqrt(xsize*ysize)

    def components_to_screen(self, coords):
        return self.projection_to_screen(self.projection.components_to_projection(coords))

    def projection_to_screen(self, coords):
        zoomed = (coords - self.screen_center) / self.screen_size
        screen = (zoomed + np.array([self.width, self.height])/2)
        return np.int32(screen * FLIP_Y + [0, self.height])

    def screen_to_projection(self, screen_coords):
        zoomed = ((screen_coords - [0, self.height])*FLIP_Y) - np.array([self.width, self.height])/2
        return (zoomed * self.screen_size) + self.screen_center
    
    def components_to_colors(self, coords):
        while coords.shape[1] < 3:
            coords = np.concatenate([coords, -coords, coords], axis=1)
        return np.clip(np.int32(coords[...,2:5]*3/self.scale + 128), 25, 230)
    
    def update_screenpts(self):
        self.screenpts = self.components_to_screen(self.array)

    def update_colors(self):
        self.colors = self.default_colors
        
    def constrain_to_screen(self, points):
        return np.clip(points,
          np.int32([1., 1.]), np.int32([self.width-2, self.height-2])).T
    
    def distances_from_mouse(self, coords):
        mouse = np.int32([self.mouseX, self.mouseY])
        offsets = self.screenpts - mouse
        return np.sqrt(np.sum(offsets*offsets, axis=1))

    def get_nearest_point(self):
        return np.argmin(self.distances_from_mouse(self.array))

    def select_nearest_point(self):
        self.selected_index = self.get_nearest_point()
        self.selectEvent(self.selected_index)

    def selected_vector(self):
        return self.array[self.selected_index]

    def selected_label(self):
        return self.labels[self.selected_index]
    
    def selectEvent(self, index):
        for layer in self.layers:
            layer.selectEvent(index)
        self.emit(SIGNAL('svdSelectEvent()'))

    def focus_on_point(self, text):
        index = self.labels.index(text)
        if index is None: return

        coords = self.projection.components_to_projection(self.array[index])
        if not self.is_point_on_screen(coords):
            self.screen_center = coords
        self.selected_index = index
        self.selectEvent(index)

    def paintEvent(self, event):
        if self.paint_lock.tryLock():
            QWidget.paintEvent(self, event)
            self.painter.begin(self)
            self.painter.setRenderHint(QPainter.Antialiasing, True)
            self.painter.setRenderHint(QPainter.TextAntialiasing, True)
            try:
                for layer in self.layers:
                    layer.draw(self.painter)
            finally:
                self.painter.end()
                self.paint_lock.unlock()

    def resizeEvent(self, sizeEvent):
        self.width = sizeEvent.size().width()
        self.height = sizeEvent.size().height()
        for layer in self.layers:
            layer.resize(self.width, self.height)

    def mouseMoveEvent(self, mouseEvent):
        point = mouseEvent.pos()
        self.mouseX = point.x()
        self.mouseY = point.y()
        for layer in self.layers: layer.mouseMoveEvent(mouseEvent)
        if self.leftMouseDown() or self.rightMouseDown():
            self.activate_timer()
        elif self.timer_ticks >= TIMER_MAX:
            self.update()
    
    def timerEvent(self):
        self.projection.timerEvent()
        for layer in self.layers: layer.timerEvent()
        self.update_screenpts()
        self.update()
        self.age_timer()
    
    def updateMouseButtons(self, event):
        self.buttons = event.buttons()
        self.modifiers = event.modifiers()

    def leftMouseDown(self):
        '''
        Checks if the left mouse button was pressed at the time of the last event.
        
        Right mouse clicks can be faked by holding a modifier (Ctrl on Macs, Logo key on Windows).
        '''
        return (self.buttons & Qt.LeftButton) and not (self.modifiers & RIGHT_BUTTON_MODIFIER)

    def rightMouseDown(self):
        '''
        Checks if the right mouse button was pressed at the time of the last event.
        
        Right mouse clicks can be faked by holding a modifier (Ctrl on Macs, Logo key on Windows).
        '''
        return (self.buttons & Qt.RightButton) or (self.buttons & Qt.LeftButton and self.modifiers & RIGHT_BUTTON_MODIFIER)

    def mousePressEvent(self, mouseEvent):
        self.updateMouseButtons(mouseEvent)
        for layer in self.layers: layer.mousePressEvent(mouseEvent)
        self.activate_timer()

    def mouseReleaseEvent(self, mouseEvent):
        self.updateMouseButtons(mouseEvent)
        for layer in self.layers: layer.mouseReleaseEvent(mouseEvent)
        self.activate_timer()

    def wheelEvent(self, mouseEvent):
        for layer in self.layers: layer.wheelEvent(mouseEvent)
        self.activate_timer()

    def dropLabel(self, index, label):
        self.refreshData(self, index)

    def refreshData(self):
        self.update_screenpts()
        self.default_colors = self.components_to_colors(self.array)[:]
        self.update_colors()
        self.update()

def get_conceptnet():
    from csc.conceptnet4.analogyspace import conceptnet_2d_from_db
    return conceptnet_2d_from_db('en').normalized()

def main(app):
    if len(sys.argv) > 1:
        picklefile = sys.argv[1]
    else:
        picklefile = 'aspace.pickle'
    cnet = get_picklecached_thing('cnet.pickle', get_conceptnet)
    matrix = get_picklecached_thing(picklefile)
    view = SVDViewer.make_svdview(cnet, matrix)
    view.setGeometry(300, 300, 800, 600)
    view.setWindowTitle("SVDview")
    view.show()
    app.exec_()

class SVDViewPanel(QWidget):
    axis_re = re.compile(r"^Axis (\d+)$")
    def __init__(self):
        QWidget.__init__(self)
        self.layout = QGridLayout(self)
        self.viewer = None
        
        self.x_label = QLabel("X axis:")
        self.x_chooser = QComboBox()
        self.x_chooser.setEditable(True)
        self.y_label = QLabel("Y axis:")
        self.y_chooser = QComboBox()
        self.y_chooser.setEditable(True)
        # TODO: add completers
        self.nav_reset = QPushButton("&Reset view")

        self.layout.addWidget(self.x_label, 1, 0)
        self.layout.addWidget(self.x_chooser, 1, 1)
        self.layout.addWidget(self.y_label, 1, 3)
        self.layout.addWidget(self.y_chooser, 1, 4)
        self.layout.addWidget(self.nav_reset, 1, 6)
        self.layout.setColumnStretch(1, 1)
        self.layout.setColumnStretch(4, 1)
        self.layout.setRowStretch(0, 1)

        self.connect(self.nav_reset, SIGNAL("clicked()"), self.reset_view)
        self.connect(self.x_chooser, SIGNAL("currentIndexChanged(QString)"), self.set_x_from_string)
        self.connect(self.y_chooser, SIGNAL("currentIndexChanged(QString)"), self.set_y_from_string)
    
        self.connect(self.x_chooser, SIGNAL("activate(QString)"), self.set_x_from_string)
    def activate(self, blend, svd, canonical):
        self.deactivate()
        self.viewer = SVDViewer.make_svdview(blend, svd, canonical)
        self.layout.addWidget(self.viewer, 0, 0, 1, 7)
        self.setup_choosers(canonical)
        self.connect(self.viewer.projection, SIGNAL('rotated()'), self.update_choosers)
        self.connect(self.viewer, SIGNAL('svdSelectEvent()'), self.viewer_selected)

    
    def viewer_selected(self):
        self.emit(SIGNAL('svdSelectEvent()'))
                

    #These should probably be placed somewhere else but oh well
    def get_selected_label(self):
        if self.viewer is not None:
            return self.viewer.selected_label()
        else:
            return None
            
    def setup_choosers(self, canonical=[]):
        for chooser in (self.x_chooser, self.y_chooser):
            chooser.clear()
            pcs = ["", "Default"] + ["Axis %d" % i for i in xrange(self.viewer.k)]
            chooser.insertItems(0, pcs)
            chooser.insertItems(2, canonical)
            chooser.setCompleter(QCompleter(self.viewer.labels))
            chooser.setCurrentIndex(1)

    def update_choosers(self):
        matrix = self.viewer.projection.target_matrix
        xmags = np.sort(matrix[:,0])
        xarg = np.argmax(matrix[:,0])
        ymags = np.sort(matrix[:,1])
        yarg = np.argmax(matrix[:,1])

        if xmags[-1] > 10*xmags[-2]:
            self.x_chooser.setCurrentIndex(self.x_chooser.findText("Axis %d" % xarg))
        else:
            self.x_chooser.setCurrentIndex(0)
        if ymags[-1] > 10*ymags[-2]:
            self.y_chooser.setCurrentIndex(self.y_chooser.findText("Axis %d" % yarg))
        else:
            self.y_chooser.setCurrentIndex(0)

    def set_x_from_string(self, string):
        self.set_axis_from_string(0, string)

    def set_y_from_string(self, string):
        self.set_axis_from_string(1, string)

    def set_axis_from_string(self, axis, string):
        if self.viewer is not None:
            axismatch = SVDViewPanel.axis_re.search(string)
            if axismatch:
                # This describes a particular principal component
                pc = int(axismatch.group(1))
                self.viewer.set_axis_to_pc(axis, pc)
            elif string == 'Default':
                if axis == 0: self.viewer.set_default_x_axis()
                if axis == 1: self.viewer.set_default_y_axis()
            else:
                self.viewer.set_axis_to_text(axis, string)

    def next_axis(self):
        if self.viewer is not None:
            if (self.x_chooser.currentIndex() == 1 and 
                self.y_chooser.currentIndex() == 1):
                self.first_two_axes()
            else:
                self.viewer.projection.next_axis()
                self.viewer.activate_timer()

    def prev_axis(self):
        if self.viewer is not None:
            if (self.x_chooser.currentIndex() == 1 and 
                self.y_chooser.currentIndex() == 1):
                self.first_two_axes()
            else:
                self.viewer.projection.prev_axis()
                self.viewer.activate_timer()

    def first_two_axes(self):
        """Go from the default projection to axes 0 and 1. Yes, those are
        different."""
        self.set_axis_from_string(0, "Axis 0")
        self.set_axis_from_string(1, "Axis 1")
        self.update_choosers()

    def deactivate(self):
        if self.viewer is not None:
            self.disconnect(self.viewer.projection, SIGNAL('rotated()'), self.update_choosers)
            self.disconnect(self.viewer, SIGNAL('svdSelectEvent()'), self.viewer_selected)
            self.viewer.hide()
            del self.viewer
            self.viewer = None

    def reset_view(self):
        if self.viewer is not None:
            self.viewer.reset_view()
            self.x_chooser.setCurrentIndex(self.x_chooser.findText("Default"))
            self.y_chooser.setCurrentIndex(self.y_chooser.findText("Default"))
            self.viewer.activate_timer()

    def focus_on_point(self, text):
        if self.viewer is not None:
            self.viewer.focus_on_point(text)
            self.viewer.activate_timer()

    def sizeHint(self):
        return QSize(600, 800)

    def find_point(self, string):
        string = unicode(string)
        if self.viewer is not None:
            if string in self.viewer.labels:
                self.focus_on_point(string)
                return True
            else:
                return False

if __name__ == '__main__':
    main(app)