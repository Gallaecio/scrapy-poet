.. _`overrides`:

=========
Overrides
=========
This functionality opens the door to configure specific Page Objects depending
on the request URL domain. Please have a look to :ref:`intro-tutorial` to
learn the basics about overrides before digging deeper in the content of this
page.

Page Objects refinement
=======================

Any ``Injectable`` or page input can be overridden. But the overriding
mechanism stops for the children of any already overridden type. This opens
the door to refining existing Page Objects without getting trapped in a cyclic
dependency. For example, you might have an existing Page Object for book extraction:

.. code-block:: python

    class BookPage(ItemPage):
        def to_item(self):
            ...

Imagine this Page Object obtains its data from an external API.
Therefore, it is not holding the page HTML code.
But you want to extract an additional attribute (e.g. ``ISBN``) that
was not extracted by the original Page Object.
Using inheritance is not enough in this case, though.
No problem, you can just override it
using the following Page Object:

.. code-block:: python

    class ISBNBookPage(ItemWebPage):

        def __init__(self, response: ResponseData, book_page: BookPage):
            super().__init__(response)
            self.book_page = book_page

        def to_item(self):
            item = self.book_page.to_item()
            item['isbn'] = self.css(".isbn-class::text").get()
            return item

And then override it for a particular domain using ``settings.py``:

.. code-block:: python

    SCRAPY_POET_OVERRIDES = [
        ("example.com", ISBNBookPage, BookPage)
    ]

This new Page Objects gets the original ``BookPage`` as dependency and enrich
the obtained item with the ISBN from the page HTML.

.. note::

    By design overrides rules are not applied to ``ISBNBookPage`` dependencies
    as it is an overridden type. If they were,
    it would end up in a cyclic dependency error because ``ISBNBookPage`` would
    depend on itself!

.. note::

    This is an alternative more compact way of writing the above Page Object
    using ``attr.define``:

    .. code-block:: python

        @attr.define
        class ISBNBookPage(ItemWebPage):
            book_page: BookPage

            def to_item(self):
                item = self.book_page.to_item()
                item['isbn'] = self.css(".isbn-class::text").get()
                return item


Overrides rules
===============

The default way of configuring the override rules is using triplets
of the form (``url pattern``, ``override_type``, ``overridden_type``). But
more complex rules can be introduced if the class ``OverrideRule``
is used. The following example configures an override that
is only applied for book pages from ``books.toscrape.com``:

.. code-block:: python

    SCRAPY_POET_OVERRIDES = [
        OverrideRule(
            for_patterns=Patterns(
                include=["books.toscrape.com/cataloge/*index.html|"],
                exclude=["/catalogue/category/"]),
            use=MyBookPage,
            instead_of=BookPage
        )
    ]

Note how category pages are excluded by using a ``exclude`` pattern.
You can find more information about the patterns syntax in the
`url-matcher <https://url-matcher.readthedocs.io/en/stable/>`_
documentation.


Decorate Page Objects with the rules
====================================

Having the rules along with the Page Objects is a good idea,
as you can identify with a single sight what the Page Object is doing
along with where it is applied. This can be done by decorating the
Page Objects with ``@handle_urls`` provided by `web-poet`_.

Let's see an example:

.. code-block:: python

    from web_poet import handle_urls

    @handle_urls("toscrape.com", BookPage)
    class BTSBookPage(BookPage):

        def to_item(self):
            return {
                'url': self.url,
                'name': self.css("title::text").get(),
            }

The ``@handle_urls`` decorator in this case is indicating that
the class ``BSTBookPage`` should be used instead of ``BookPage``
for the domain ``toscrape.com``.

In order to configure the ``scrapy-poet`` overrides automatically
using these annotations, you can directly interact with `web-poet`_'s
default registry.

For example:

.. code-block:: python

    from web_poet import default_registry, consume_modules

    # The consume_modules() must be called first if you need to load
    # rules from other packages. Otherwise, it can be omitted.
    # More info about this caveat on web-poet docs.
    consume_modules("external_package_A.po", "another_ext_package.lib")

    # To get all of the Override Rules that were declared via annotations.
    SCRAPY_POET_OVERRIDES = default_registry.get_overrides()

    # The two lines above could be mixed together via this shortcut:
    SCRAPY_POET_OVERRIDES = default_registry.get_overrides(
        consume=["external_package_A.po", "another_ext_package.lib"]
    )

    # Or, you could even extract the rules on a specific subpackage or module.
    SCRAPY_POET_OVERRIDES = default_registry.get_overrides(
        filters=["external_page_objects_package", "another_page_object_package.module_1"]
    )

The ``get_overrides()`` method of the ``default_registry`` above returns
``List[OverrideRule]`` that were declared using `web-poet`_'s ``@handle_urls()``
annotation. This is much more convenient that manually defining all of the 
`OverrideRule``. Take note that since ``SCRAPY_POET_OVERRIDES`` is structured as
``List[OverrideRule]``, you can easily modify it later on if needed.

.. note::

    For more info and advanced features of `web-poet`_'s ``@handle_urls``
    and its registry, kindly read the `web-poet <https://web-poet.readthedocs.io>`_
    documentation regarding Overrides.

Overrides registry
==================

The overrides registry is responsible for informing whether there exists an
override for a particular type for a given request. The default overrides
registry allows to configure these rules using patterns that follow the
`url-matcher <https://url-matcher.readthedocs.io/en/stable/>`_ syntax. These rules can be configured using the
``SCRAPY_POET_OVERRIDES`` setting, as it has been seen in the :ref:`intro-tutorial`
example.

But the registry implementation can be changed at convenience. A different
registry implementation can be configured using the property
``SCRAPY_POET_OVERRIDES_REGISTRY`` in ``settings.py``. The new registry
must be a subclass of ``scrapy_poet.overrides.OverridesRegistryBase``
and must implement the method ``overrides_for``. As other Scrapy components,
it can be initialized from the ``from_crawler`` class method if implemented.
This might be handy to be able to access settings, stats, request meta, etc.

