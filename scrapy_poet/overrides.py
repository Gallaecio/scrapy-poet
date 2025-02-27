import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Dict, Mapping, Callable, Iterable, Union, Tuple, Optional, List

from scrapy import Request
from scrapy.crawler import Crawler
from url_matcher import Patterns, URLMatcher
from url_matcher.util import get_domain
from web_poet.overrides import OverrideRule


logger = logging.getLogger(__name__)

RuleAsTuple = Union[Tuple[str, Callable, Callable], List]
RuleFromUser = Union[RuleAsTuple, OverrideRule]


class OverridesRegistryBase(ABC):
    @abstractmethod
    def overrides_for(self, request: Request) -> Mapping[Callable, Callable]:
        """
        Return a ``Mapping`` (e.g. a ``dict``) with type translation rules.
        The key is the source type that is wanted to be replaced by
        value, which is also a type.
        """
        pass


class OverridesRegistry(OverridesRegistryBase):
    """
    Overrides registry that reads the overrides from the ``SCRAPY_POET_OVERRIDES``
    in the spider settings. It is a list and each rule can be a tuple or an
    instance of the class :py:class:`web_poet.overrides.OverrideRule`.

    If a tuple is provided:

        - the **first** element is the pattern to match the URL,
        - the **second** element is the type to be used instead of the type in
          the **third** element.

    Another way to see it for the URLs that match the pattern ``tuple[0]`` use
    ``tuple[1]`` instead of ``tuple[2]``.

    Example of overrides configuration:

    .. code-block:: python

        from url_matcher import Patterns
        from scrapy_poet.overrides import OverrideRule


        SCRAPY_POET_OVERRIDES = [
            # Option 1
            ("books.toscrape.com", ISBNBookPage, BookPage),

            # Option 2
            OverrideRule(
                for_patterns=Patterns(["books.toscrape.com"]),
                use=MyBookListPage,
                instead_of=BookListPage,
            ),
        ]

    .. _web-poet: https://web-poet.readthedocs.io

    Now, if you've used web-poet_'s built-in functionality to directly create
    the :py:class:`web_poet.overrides.OverrideRule` in the Page Object via the
    :py:func:`web_poet.handle_urls` annotation, you can quickly import them via
    the following code below. It finds all the rules annotated using web-poet_'s
    :py:func:`web_poet.handle_urls` as a decorator that were registered into
    ``web_poet.default_registry`` (an instance of
    :py:class:`web_poet.overrides.PageObjectRegistry`).

    .. code-block:: python

        from web_poet import default_registry, consume_modules

        # The consume_modules() must be called first if you need to properly
        # import rules from other packages. Otherwise, it can be omitted.
        # More info about this caveat on web-poet docs.
        consume_modules("external_package_A.po", "another_ext_package.lib")
        SCRAPY_POET_OVERRIDES = default_registry.get_overrides()

    Make sure to call :py:func:`web_poet.overrides.consume_modules` beforehand.
    More info on this at web-poet_.
    """

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> Crawler:
        return cls(crawler.settings.getlist("SCRAPY_POET_OVERRIDES", []))

    def __init__(self, rules: Optional[Iterable[RuleFromUser]] = None) -> None:
        self.rules: List[OverrideRule] = []
        self.matcher: Dict[Callable, URLMatcher] = defaultdict(URLMatcher)
        for rule in rules or []:
            self.add_rule(rule)
        logger.debug(f"List of parsed OverrideRules:\n{self.rules}")

    def add_rule(self, rule: RuleFromUser) -> None:
        if isinstance(rule, (tuple, list)):
            if len(rule) != 3:
                raise ValueError(
                    f"Invalid overrides rule: {rule}. Rules as tuples must have "
                    f"3 elements: (1) the pattern, (2) the PO class used as a "
                    f"replacement and (3) the PO class to be replaced."
                )
            pattern, use, instead_of = rule
            rule = OverrideRule(
                for_patterns=Patterns([pattern]), use=use, instead_of=instead_of
            )
        self.rules.append(rule)
        self.matcher[rule.instead_of].add_or_update(
            len(self.rules) - 1, rule.for_patterns
        )

    def overrides_for(self, request: Request) -> Mapping[Callable, Callable]:
        overrides: Dict[Callable, Callable] = {}
        for instead_of, matcher in self.matcher.items():
            rule_id = matcher.match(request.url)
            if rule_id is not None:
                overrides[instead_of] = self.rules[rule_id].use
        return overrides
