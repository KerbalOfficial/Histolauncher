'''
Plyer
=====

'''

__all__ = ('notification')

__version__ = '2.1.0'


from core.libraries.plyer import facades
from core.libraries.plyer.utils import Proxy

#: Notification proxy to :class:`plyer.facades.Notification`
notification = Proxy('notification', facades.Notification)