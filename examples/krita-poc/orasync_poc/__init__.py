from krita import Krita

from .extension import OrasyncPocExtension

Krita.instance().addExtension(OrasyncPocExtension(Krita.instance()))

