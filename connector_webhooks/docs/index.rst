Connector Webhooks Documentation
================================

This documentation is split by the two audiences that normally interact with
this addon.

Choose your track
-----------------

Developers
  Build business connector addons that let one backend own one inbound endpoint
  and one outbound endpoint through a shared relational layer.

Maintainers
  Evolve the connector-webhooks boundary, helper methods, and ownership
  constraints without pushing business behavior into the glue addon.

Shared principles
-----------------

* business logic stays in consuming backend addons
* ownership is relational and explicit on both sides
* company scope must match between backend and linked endpoint
* helper actions may lazy-sync only through consuming backend hook methods
* ``webhooks`` continues to own request, delivery, and handler behavior

Developer guides
----------------

* `Developer getting started <developer_getting_started.rst>`_

Maintainer guides
-----------------

* `Maintainer architecture <maintainer_architecture.rst>`_

Reading order
-------------

* Developers should start with `Developer getting started <developer_getting_started.rst>`_.
* Maintainers should start with `Maintainer architecture <maintainer_architecture.rst>`_.

If you need endpoint, handler, or delivery behavior beyond the ownership layer,
continue to the main ``webhooks`` addon documentation.
