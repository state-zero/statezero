"""
Exotic query equivalence tests: complex Q/filter/exclude patterns
compared side-by-side with Django ORM.

Focuses on edge cases where the StateZero client query builder might
diverge from raw Django ORM behaviour — especially around:
  - Deeply nested Q combinations
  - Multiple Q args in a single .filter() call
  - Chained .filter().filter() vs single .filter(Q & Q) on M2M
  - Exclude with compound Q
  - Mixed filter + exclude chains
  - Null handling inside Q
  - Aggregation after complex filters
  - Edge cases with empty results, overlapping conditions, etc.
"""
import uuid
from datetime import date, datetime, timezone as tz
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Q as DjangoQ, Count, Sum, Avg, Min, Max
from django.test import TestCase

from statezero.client.runtime_template import (
    Model, Q, F, configure, _field_permissions_cache,
)
from statezero.client.testing import DjangoTestTransport
from tests.django_app.models import Author, Book, Tag

User = get_user_model()


# ---------------------------------------------------------------------------
# Client model stubs
# ---------------------------------------------------------------------------

class AuthorClient(Model):
    _model_name = "django_app.author"
    _pk_field = "id"
    _relations = {}


class BookClient(Model):
    _model_name = "django_app.book"
    _pk_field = "id"
    _relations = {"author": "django_app.author"}


class TagClient(Model):
    _model_name = "django_app.tag"
    _pk_field = "id"
    _relations = {}


# ---------------------------------------------------------------------------
# Base helper
# ---------------------------------------------------------------------------

class ExoticQueryBase(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = User.objects.create_superuser(
            username="exotic_admin", password="admin", email="exotic@test.com"
        )

    def setUp(self):
        configure(transport=DjangoTestTransport(user=self.admin))
        _field_permissions_cache.clear()

    def assert_pk_set(self, client_results, orm_qs, msg=""):
        """Assert that client results match ORM queryset by PK set."""
        client_pks = {r.pk for r in client_results}
        orm_pks = set(orm_qs.values_list("pk", flat=True))
        self.assertEqual(client_pks, orm_pks, msg)

    def assert_ordered_pks(self, client_results, orm_qs, msg=""):
        """Assert that client results match ORM queryset by ordered PK list."""
        client_pks = [r.pk for r in client_results]
        orm_pks = list(orm_qs.values_list("pk", flat=True))
        self.assertEqual(client_pks, orm_pks, msg)


# ===========================================================================
# Nested Q combinations (no M2M, should always match)
# ===========================================================================

class TestNestedQParity(ExoticQueryBase):
    """Complex nested Q on simple (non-M2M) fields."""

    def setUp(self):
        super().setUp()
        self.a = Author.objects.create(name="alice", age=30, rating=4.5)
        self.b = Author.objects.create(name="bob", age=25, rating=3.0)
        self.c = Author.objects.create(name="charlie", age=35, rating=5.0)
        self.d = Author.objects.create(name="diana", age=28, rating=2.0)
        self.e = Author.objects.create(name="eve", age=40, rating=4.0)

    # --- (A | B) & C ---
    def test_or_then_and(self):
        """(name=alice | name=bob) & age>=28"""
        results = AuthorClient.objects.filter(
            (Q(name="alice") | Q(name="bob")) & Q(age__gte=28)
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            (DjangoQ(name="alice") | DjangoQ(name="bob")) & DjangoQ(age__gte=28)
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    # --- A & (B | C) ---
    def test_and_then_or(self):
        """age>=30 & (rating>=5 | name=alice)"""
        results = AuthorClient.objects.filter(
            Q(age__gte=30) & (Q(rating__gte=5.0) | Q(name="alice"))
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            DjangoQ(age__gte=30) & (DjangoQ(rating__gte=5.0) | DjangoQ(name="alice"))
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    # --- (A | B) & (C | D) ---
    def test_or_and_or(self):
        """(name=alice | name=charlie) & (age>=35 | rating>=4.5)"""
        results = AuthorClient.objects.filter(
            (Q(name="alice") | Q(name="charlie")) & (Q(age__gte=35) | Q(rating__gte=4.5))
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            (DjangoQ(name="alice") | DjangoQ(name="charlie"))
            & (DjangoQ(age__gte=35) | DjangoQ(rating__gte=4.5))
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    # --- A | B | C (triple OR) ---
    def test_triple_or(self):
        results = AuthorClient.objects.filter(
            Q(name="alice") | Q(name="bob") | Q(name="eve")
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            DjangoQ(name="alice") | DjangoQ(name="bob") | DjangoQ(name="eve")
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    # --- A & B & C (triple AND via chained Q) ---
    def test_triple_and(self):
        results = AuthorClient.objects.filter(
            Q(age__gte=25) & Q(age__lte=35) & Q(rating__gte=3.0)
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            age__gte=25, age__lte=35, rating__gte=3.0
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    # --- (A | B) | (C | D) (nested ORs) ---
    def test_nested_ors(self):
        results = AuthorClient.objects.filter(
            (Q(name="alice") | Q(name="bob")) | (Q(name="charlie") | Q(name="diana"))
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            DjangoQ(name__in=["alice", "bob", "charlie", "diana"])
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    # --- deeply nested: ((A | B) & C) | D ---
    def test_deep_nesting(self):
        """((name=alice | name=bob) & age>=28) | name=eve"""
        results = AuthorClient.objects.filter(
            ((Q(name="alice") | Q(name="bob")) & Q(age__gte=28)) | Q(name="eve")
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            ((DjangoQ(name="alice") | DjangoQ(name="bob")) & DjangoQ(age__gte=28))
            | DjangoQ(name="eve")
        ).order_by("id")
        self.assert_ordered_pks(results, orm)


# ===========================================================================
# Exclude with compound Q
# ===========================================================================

class TestExcludeCompoundQParity(ExoticQueryBase):

    def setUp(self):
        super().setUp()
        self.a = Author.objects.create(name="alpha", age=20, rating=1.0)
        self.b = Author.objects.create(name="beta", age=30, rating=2.0)
        self.c = Author.objects.create(name="gamma", age=40, rating=3.0)
        self.d = Author.objects.create(name="delta", age=50, rating=4.0)

    def test_exclude_simple_q(self):
        results = AuthorClient.objects.exclude(
            Q(name="alpha")
        ).order_by("id").fetch()
        orm = Author.objects.exclude(name="alpha").order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_exclude_or_q(self):
        """Exclude where name=alpha OR name=beta"""
        results = AuthorClient.objects.exclude(
            Q(name="alpha") | Q(name="beta")
        ).order_by("id").fetch()
        orm = Author.objects.exclude(
            DjangoQ(name="alpha") | DjangoQ(name="beta")
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_exclude_and_q(self):
        """Exclude where age>=30 AND rating<=2.0"""
        results = AuthorClient.objects.exclude(
            Q(age__gte=30) & Q(rating__lte=2.0)
        ).order_by("id").fetch()
        orm = Author.objects.exclude(
            DjangoQ(age__gte=30) & DjangoQ(rating__lte=2.0)
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_filter_then_exclude_q(self):
        """Filter age>=25 then exclude name=gamma"""
        results = (
            AuthorClient.objects
            .filter(age__gte=25)
            .exclude(Q(name="gamma"))
            .order_by("id").fetch()
        )
        orm = Author.objects.filter(age__gte=25).exclude(name="gamma").order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_exclude_then_filter(self):
        """Exclude first, then filter."""
        results = (
            AuthorClient.objects
            .exclude(name="alpha")
            .filter(age__lte=40)
            .order_by("id").fetch()
        )
        orm = Author.objects.exclude(name="alpha").filter(age__lte=40).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_multiple_excludes(self):
        """Chain multiple exclude calls."""
        results = (
            AuthorClient.objects
            .exclude(name="alpha")
            .exclude(name="delta")
            .order_by("id").fetch()
        )
        orm = Author.objects.exclude(name="alpha").exclude(name="delta").order_by("id")
        self.assert_ordered_pks(results, orm)


# ===========================================================================
# Mixed filter + exclude with complex Q
# ===========================================================================

class TestMixedFilterExcludeParity(ExoticQueryBase):

    def setUp(self):
        super().setUp()
        Author.objects.create(name="mx_a", age=20, rating=1.0, is_active=True)
        Author.objects.create(name="mx_b", age=30, rating=2.0, is_active=True)
        Author.objects.create(name="mx_c", age=40, rating=3.0, is_active=False)
        Author.objects.create(name="mx_d", age=50, rating=4.0, is_active=False)
        Author.objects.create(name="mx_e", age=25, rating=5.0, is_active=True)

    def test_filter_or_then_exclude_range(self):
        """Filter (active OR high-rating), then exclude age range."""
        results = (
            AuthorClient.objects
            .filter(Q(is_active=True) | Q(rating__gte=4.0))
            .exclude(age__range=[28, 45])
            .order_by("id").fetch()
        )
        orm = (
            Author.objects
            .filter(DjangoQ(is_active=True) | DjangoQ(rating__gte=4.0))
            .exclude(age__range=[28, 45])
            .order_by("id")
        )
        self.assert_ordered_pks(results, orm)

    def test_exclude_or_then_filter(self):
        """Exclude (inactive OR low-rating), then filter age."""
        results = (
            AuthorClient.objects
            .exclude(Q(is_active=False) | Q(rating__lt=2.0))
            .filter(age__gte=25)
            .order_by("id").fetch()
        )
        orm = (
            Author.objects
            .exclude(DjangoQ(is_active=False) | DjangoQ(rating__lt=2.0))
            .filter(age__gte=25)
            .order_by("id")
        )
        self.assert_ordered_pks(results, orm)

    def test_interleaved_filter_exclude(self):
        """filter → exclude → filter chain."""
        results = (
            AuthorClient.objects
            .filter(age__gte=20)
            .exclude(rating__lt=2.0)
            .filter(is_active=True)
            .order_by("id").fetch()
        )
        orm = (
            Author.objects
            .filter(age__gte=20)
            .exclude(rating__lt=2.0)
            .filter(is_active=True)
            .order_by("id")
        )
        self.assert_ordered_pks(results, orm)


# ===========================================================================
# Q with null / isnull handling
# ===========================================================================

class TestQNullParity(ExoticQueryBase):

    def setUp(self):
        super().setUp()
        Author.objects.create(name="has_all", age=30, salary=Decimal("50000"))
        Author.objects.create(name="no_age", age=None, salary=Decimal("60000"))
        Author.objects.create(name="no_salary", age=25, salary=None)
        Author.objects.create(name="no_both", age=None, salary=None)

    def test_or_with_isnull(self):
        """age is null OR salary is null"""
        results = AuthorClient.objects.filter(
            Q(age__isnull=True) | Q(salary__isnull=True)
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            DjangoQ(age__isnull=True) | DjangoQ(salary__isnull=True)
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_and_with_isnull(self):
        """age is null AND salary is null"""
        results = AuthorClient.objects.filter(
            Q(age__isnull=True) & Q(salary__isnull=True)
        ).fetch()
        orm = Author.objects.filter(age__isnull=True, salary__isnull=True)
        self.assert_pk_set(results, orm)

    def test_exclude_null_with_filter(self):
        """Filter non-null age, exclude null salary"""
        results = (
            AuthorClient.objects
            .filter(age__isnull=False)
            .exclude(salary__isnull=True)
            .order_by("id").fetch()
        )
        orm = (
            Author.objects
            .filter(age__isnull=False)
            .exclude(salary__isnull=True)
            .order_by("id")
        )
        self.assert_ordered_pks(results, orm)

    def test_or_null_and_value(self):
        """(age is null) OR (salary >= 55000)"""
        results = AuthorClient.objects.filter(
            Q(age__isnull=True) | Q(salary__gte=55000)
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            DjangoQ(age__isnull=True) | DjangoQ(salary__gte=55000)
        ).order_by("id")
        self.assert_ordered_pks(results, orm)


# ===========================================================================
# Chained filters with FK lookups + Q
# ===========================================================================

class TestFKQueryParity(ExoticQueryBase):
    """Complex filters crossing FK boundaries."""

    def setUp(self):
        super().setUp()
        self.alice = Author.objects.create(name="fk_alice", age=30, rating=4.5)
        self.bob = Author.objects.create(name="fk_bob", age=25, rating=3.0)
        self.carol = Author.objects.create(name="fk_carol", age=35, rating=5.0)

        self.b1 = Book.objects.create(title="Algo", author=self.alice, price=Decimal("20"), pages=300, is_published=True)
        self.b2 = Book.objects.create(title="Bio", author=self.alice, price=Decimal("15"), pages=200, is_published=False)
        self.b3 = Book.objects.create(title="Chem", author=self.bob, price=Decimal("30"), pages=400, is_published=True)
        self.b4 = Book.objects.create(title="Data", author=self.carol, price=Decimal("25"), pages=350, is_published=True)
        self.b5 = Book.objects.create(title="Ethics", author=self.carol, price=Decimal("10"), pages=150, is_published=False)

    def test_fk_or(self):
        """Books by alice OR books with price > 25"""
        results = BookClient.objects.filter(
            Q(author__name="fk_alice") | Q(price__gt=25)
        ).order_by("id").fetch()
        orm = Book.objects.filter(
            DjangoQ(author__name="fk_alice") | DjangoQ(price__gt=25)
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_fk_and_across_relations(self):
        """author.age >= 30 AND published"""
        results = BookClient.objects.filter(
            Q(author__age__gte=30) & Q(is_published=True)
        ).order_by("id").fetch()
        orm = Book.objects.filter(
            author__age__gte=30, is_published=True
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_fk_nested_or_and(self):
        """(author=alice OR author=carol) AND price >= 20"""
        results = BookClient.objects.filter(
            (Q(author__name="fk_alice") | Q(author__name="fk_carol")) & Q(price__gte=20)
        ).order_by("id").fetch()
        orm = Book.objects.filter(
            (DjangoQ(author__name="fk_alice") | DjangoQ(author__name="fk_carol"))
            & DjangoQ(price__gte=20)
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_fk_exclude_with_q(self):
        """Exclude books by bob AND unpublished"""
        results = BookClient.objects.exclude(
            Q(author__name="fk_bob")
        ).exclude(
            Q(is_published=False)
        ).order_by("id").fetch()
        orm = Book.objects.exclude(
            author__name="fk_bob"
        ).exclude(
            is_published=False
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_fk_filter_exclude_interleaved(self):
        """Filter published, exclude cheap (price < 20), filter by author age."""
        results = (
            BookClient.objects
            .filter(is_published=True)
            .exclude(price__lt=20)
            .filter(author__age__gte=30)
            .order_by("id").fetch()
        )
        orm = (
            Book.objects
            .filter(is_published=True)
            .exclude(price__lt=20)
            .filter(author__age__gte=30)
            .order_by("id")
        )
        self.assert_ordered_pks(results, orm)

    def test_fk_deep_lookup_in_q(self):
        """Q with double-underscore FK traversal: author__rating__gte"""
        results = BookClient.objects.filter(
            Q(author__rating__gte=4.5) | Q(pages__gte=400)
        ).order_by("id").fetch()
        orm = Book.objects.filter(
            DjangoQ(author__rating__gte=4.5) | DjangoQ(pages__gte=400)
        ).order_by("id")
        self.assert_ordered_pks(results, orm)


# ===========================================================================
# M2M queries — known divergence area
#
# StateZero's AND handling always applies children as separate .filter()
# calls (chained-filter semantics), which for M2M means ANY/ANY matching
# rather than SAME-object matching.
#
# Django: .filter(Q(a) & Q(b)) → single filter → SAME M2M entry matches both
# StateZero: .filter(Q(a) & Q(b)) → separate filters → ANY M2M entry for each
#
# These tests document the expected behavior.
# ===========================================================================

class TestM2MQueryParity(ExoticQueryBase):
    """M2M query patterns — tests where StateZero matches chained-filter semantics."""

    def setUp(self):
        super().setUp()
        self.alice = Author.objects.create(name="m2m_alice", age=30)
        self.bob = Author.objects.create(name="m2m_bob", age=25)

        self.book1 = Book.objects.create(title="M2M_Book1", author=self.alice, price=Decimal("10"), pages=100)
        self.book2 = Book.objects.create(title="M2M_Book2", author=self.bob, price=Decimal("20"), pages=200)
        self.book3 = Book.objects.create(title="M2M_Book3", author=self.alice, price=Decimal("30"), pages=300)

        self.tag_fic = Tag.objects.create(name="m2m_fiction", priority=1)
        self.tag_fic.books.set([self.book1, self.book2])

        self.tag_sci = Tag.objects.create(name="m2m_science", priority=2)
        self.tag_sci.books.set([self.book2, self.book3])

        self.tag_empty = Tag.objects.create(name="m2m_empty", priority=0)

    def test_m2m_simple_filter(self):
        """Tags that contain a specific book."""
        results = TagClient.objects.filter(
            books__title="M2M_Book2"
        ).order_by("id").fetch()
        orm = Tag.objects.filter(books__title="M2M_Book2").order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_m2m_or_filter(self):
        """Tags containing book1 OR book3."""
        results = TagClient.objects.filter(
            Q(books__title="M2M_Book1") | Q(books__title="M2M_Book3")
        ).order_by("id").fetch()
        orm = Tag.objects.filter(
            DjangoQ(books__title="M2M_Book1") | DjangoQ(books__title="M2M_Book3")
        ).distinct().order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_m2m_chained_filters_any_any(self):
        """
        Chained .filter().filter() on M2M → ANY/ANY semantics.
        Tag has a book by alice AND (separately) a book by bob.
        Both fiction (book1=alice, book2=bob) and science (book2=bob, book3=alice) match.

        StateZero should match Django's chained-filter behavior.
        """
        results = (
            TagClient.objects
            .filter(books__author__name="m2m_alice")
            .filter(books__author__name="m2m_bob")
            .order_by("id").fetch()
        )
        orm = (
            Tag.objects
            .filter(books__author__name="m2m_alice")
            .filter(books__author__name="m2m_bob")
            .distinct()
            .order_by("id")
        )
        self.assert_ordered_pks(results, orm)

    def test_m2m_compound_q_and_same_field_matches_django(self):
        """
        When Q(a) & Q(b) target the SAME field of the M2M-related model,
        chained vs single filter produces the same result (both empty here,
        because no single book can have two different titles).
        """
        results = TagClient.objects.filter(
            Q(books__title="M2M_Book1") & Q(books__title="M2M_Book3")
        ).order_by("id").fetch()
        # Both chained and single filter return nothing — no book has two titles
        self.assertEqual(len(results), 0)

    def test_m2m_compound_q_different_fields_is_chained_semantics(self):
        """
        KNOWN DIVERGENCE: When Q(a) & Q(b) target DIFFERENT fields of the
        M2M-related model, StateZero uses chained-filter (ANY/ANY) semantics
        while Django's single .filter(Q(a) & Q(b)) uses SAME-object semantics.

        tag_fic has: book1 (title=M2M_Book1, author=alice) and
                     book2 (title=M2M_Book2, author=bob)

        Chained filter: tag has ANY book with title=M2M_Book1 (book1)
                        AND ANY book by bob (book2) → matches tag_fic
        Single filter:  tag has SAME book with title=M2M_Book1 AND author=bob
                        → no such book exists → empty
        """
        results = TagClient.objects.filter(
            Q(books__title="M2M_Book1") & Q(books__author__name="m2m_bob")
        ).order_by("id").fetch()

        # StateZero uses chained-filter → matches tag_fic
        orm_chained = (
            Tag.objects
            .filter(books__title="M2M_Book1")
            .filter(books__author__name="m2m_bob")
            .distinct()
            .order_by("id")
        )
        self.assert_ordered_pks(results, orm_chained)
        self.assertEqual(len(results), 1, "StateZero (chained) finds tag_fic")

        # Django single-filter would find nothing (SAME-object semantics)
        orm_single = Tag.objects.filter(
            DjangoQ(books__title="M2M_Book1") & DjangoQ(books__author__name="m2m_bob")
        ).distinct().order_by("id")
        self.assertEqual(orm_single.count(), 0, "Django single-filter finds nothing")

    def test_m2m_exclude_simple(self):
        """Exclude tags with a specific book."""
        results = TagClient.objects.exclude(
            books__title="M2M_Book1"
        ).order_by("id").fetch()
        orm = Tag.objects.exclude(books__title="M2M_Book1").order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_m2m_filter_through_fk(self):
        """M2M → FK traversal: tags whose books are by alice."""
        results = TagClient.objects.filter(
            books__author__name="m2m_alice"
        ).order_by("id").fetch()
        orm = Tag.objects.filter(
            books__author__name="m2m_alice"
        ).distinct().order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_m2m_filter_with_value_lookup(self):
        """M2M with value-based lookup: tags with books priced > 15.

        NOTE: StateZero does NOT apply .distinct() on M2M queries,
        so duplicates can appear when a tag has multiple matching books.
        This matches raw Django behavior (without .distinct()).
        """
        results = TagClient.objects.filter(
            books__price__gt=15
        ).order_by("id").fetch()
        # Compare against raw Django (no .distinct()) — both produce duplicates
        orm = Tag.objects.filter(
            books__price__gt=15
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_m2m_duplicates_without_distinct(self):
        """
        EDGE CASE: M2M joins produce duplicate rows when one parent has
        multiple matching children. StateZero passes these through
        (matches raw Django), whereas many users might expect .distinct().

        tag_sci has book2 ($20) and book3 ($30) — both match price > 15.
        So tag_sci appears TWICE in results.
        """
        results = TagClient.objects.filter(
            books__price__gt=15
        ).order_by("id").fetch()
        result_pks = [r.pk for r in results]
        # tag_sci should appear twice
        self.assertEqual(result_pks.count(self.tag_sci.pk), 2,
                         "M2M duplicate: tag_sci matched through 2 books")


# ===========================================================================
# Complex __in, __range, and mixed lookups in Q
# ===========================================================================

class TestComplexLookupsParity(ExoticQueryBase):

    def setUp(self):
        super().setUp()
        for i, (name, age, rating) in enumerate([
            ("in_a", 20, 1.0), ("in_b", 25, 2.0), ("in_c", 30, 3.0),
            ("in_d", 35, 4.0), ("in_e", 40, 5.0),
        ]):
            Author.objects.create(name=name, age=age, rating=rating)

    def test_in_combined_with_or(self):
        """__in lookup inside OR"""
        results = AuthorClient.objects.filter(
            Q(name__in=["in_a", "in_b"]) | Q(age__gte=40)
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            DjangoQ(name__in=["in_a", "in_b"]) | DjangoQ(age__gte=40)
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_range_combined_with_and(self):
        """__range inside AND"""
        results = AuthorClient.objects.filter(
            Q(age__range=[25, 35]) & Q(rating__gte=3.0)
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            age__range=[25, 35], rating__gte=3.0
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_in_excludes_with_range(self):
        """Exclude __in combined with filter __range."""
        results = (
            AuthorClient.objects
            .filter(age__range=[20, 40])
            .exclude(name__in=["in_b", "in_d"])
            .order_by("id").fetch()
        )
        orm = (
            Author.objects
            .filter(age__range=[20, 40])
            .exclude(name__in=["in_b", "in_d"])
            .order_by("id")
        )
        self.assert_ordered_pks(results, orm)

    def test_startswith_endswith_or(self):
        """String lookups in OR"""
        results = AuthorClient.objects.filter(
            Q(name__startswith="in_a") | Q(name__endswith="_e")
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            DjangoQ(name__startswith="in_a") | DjangoQ(name__endswith="_e")
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_icontains_and_gte(self):
        """Case-insensitive contains AND numeric gte"""
        results = AuthorClient.objects.filter(
            Q(name__icontains="IN_") & Q(rating__gte=3.0)
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            DjangoQ(name__icontains="IN_") & DjangoQ(rating__gte=3.0)
        ).order_by("id")
        self.assert_ordered_pks(results, orm)


# ===========================================================================
# Edge cases: empty results, overlapping, all-match, none-match
# ===========================================================================

class TestEdgeCasesParity(ExoticQueryBase):

    def setUp(self):
        super().setUp()
        Author.objects.create(name="edge_a", age=30)
        Author.objects.create(name="edge_b", age=40)

    def test_filter_no_match(self):
        """Filter that matches nothing."""
        results = AuthorClient.objects.filter(name="nonexistent").fetch()
        self.assertEqual(len(results), 0)
        self.assertEqual(Author.objects.filter(name="nonexistent").count(), 0)

    def test_filter_all_match(self):
        """Filter that matches everything."""
        results = AuthorClient.objects.filter(
            age__gte=0
        ).order_by("id").fetch()
        orm = Author.objects.filter(age__gte=0).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_contradictory_filter_and_exclude(self):
        """Filter + exclude that cancel out all results."""
        results = (
            AuthorClient.objects
            .filter(name="edge_a")
            .exclude(name="edge_a")
            .fetch()
        )
        self.assertEqual(len(results), 0)

    def test_overlapping_or_conditions(self):
        """OR with overlapping conditions — should not duplicate."""
        results = AuthorClient.objects.filter(
            Q(age__gte=30) | Q(age__gte=35)
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            DjangoQ(age__gte=30) | DjangoQ(age__gte=35)
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_redundant_filter_chain(self):
        """Multiple filters that are redundant — should still work."""
        results = (
            AuthorClient.objects
            .filter(age__gte=30)
            .filter(age__gte=30)
            .filter(age__gte=30)
            .order_by("id").fetch()
        )
        orm = Author.objects.filter(age__gte=30).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_or_with_impossible_branch(self):
        """OR where one branch is impossible."""
        results = AuthorClient.objects.filter(
            Q(name="edge_a") | Q(name="nonexistent_zzz")
        ).fetch()
        orm = Author.objects.filter(
            DjangoQ(name="edge_a") | DjangoQ(name="nonexistent_zzz")
        )
        self.assert_pk_set(results, orm)


# ===========================================================================
# Aggregation after complex filters
# ===========================================================================

class TestAggregationAfterExoticFiltersParity(ExoticQueryBase):

    def setUp(self):
        super().setUp()
        Author.objects.create(name="agg_a", age=10, rating=1.0, salary=Decimal("10000"))
        Author.objects.create(name="agg_b", age=20, rating=2.0, salary=Decimal("20000"))
        Author.objects.create(name="agg_c", age=30, rating=3.0, salary=Decimal("30000"))
        Author.objects.create(name="agg_d", age=40, rating=4.0, salary=Decimal("40000"))
        Author.objects.create(name="agg_e", age=50, rating=5.0, salary=Decimal("50000"))

    def test_count_after_or_filter(self):
        client_count = AuthorClient.objects.filter(
            Q(age__lte=20) | Q(age__gte=40)
        ).count()
        orm_count = Author.objects.filter(
            DjangoQ(age__lte=20) | DjangoQ(age__gte=40)
        ).count()
        self.assertEqual(client_count, orm_count)

    def test_sum_after_exclude(self):
        client_sum = (
            AuthorClient.objects
            .exclude(name__in=["agg_a", "agg_e"])
            .sum("age")
        )
        orm_sum = (
            Author.objects
            .exclude(name__in=["agg_a", "agg_e"])
            .aggregate(s=Sum("age"))["s"]
        )
        self.assertEqual(client_sum, orm_sum)

    def test_avg_after_complex_chain(self):
        client_avg = (
            AuthorClient.objects
            .filter(Q(age__gte=20) | Q(rating__gte=4.0))
            .exclude(name="agg_b")
            .avg("age")
        )
        orm_avg = (
            Author.objects
            .filter(DjangoQ(age__gte=20) | DjangoQ(rating__gte=4.0))
            .exclude(name="agg_b")
            .aggregate(a=Avg("age"))["a"]
        )
        self.assertAlmostEqual(float(client_avg), float(orm_avg), places=2)

    def test_min_max_after_filter(self):
        client_min = AuthorClient.objects.filter(age__gte=20).min("salary")
        client_max = AuthorClient.objects.filter(age__gte=20).max("salary")
        orm_min = Author.objects.filter(age__gte=20).aggregate(m=Min("salary"))["m"]
        orm_max = Author.objects.filter(age__gte=20).aggregate(m=Max("salary"))["m"]
        self.assertEqual(str(client_min), str(orm_min))
        self.assertEqual(str(client_max), str(orm_max))

    def test_exists_after_complex_filter(self):
        exists = AuthorClient.objects.filter(
            (Q(age__gte=100) | Q(name="nonexistent"))
        ).exists()
        orm_exists = Author.objects.filter(
            DjangoQ(age__gte=100) | DjangoQ(name="nonexistent")
        ).exists()
        self.assertEqual(exists, orm_exists)
        self.assertFalse(exists)

    def test_first_last_after_complex_filter(self):
        first = AuthorClient.objects.filter(
            Q(age__gte=20) & Q(age__lte=40)
        ).order_by("age").first()
        last = AuthorClient.objects.filter(
            Q(age__gte=20) & Q(age__lte=40)
        ).order_by("age").last()

        orm_first = Author.objects.filter(age__gte=20, age__lte=40).order_by("age").first()
        orm_last = Author.objects.filter(age__gte=20, age__lte=40).order_by("age").last()

        self.assertEqual(first.pk, orm_first.pk)
        self.assertEqual(last.pk, orm_last.pk)


# ===========================================================================
# Multiple positional Q args in .filter() — all become separate AND children
# ===========================================================================

class TestMultipleQArgsParity(ExoticQueryBase):

    def setUp(self):
        super().setUp()
        Author.objects.create(name="mq_a", age=20, rating=3.0, is_active=True)
        Author.objects.create(name="mq_b", age=30, rating=4.0, is_active=True)
        Author.objects.create(name="mq_c", age=40, rating=5.0, is_active=False)

    def test_two_q_args(self):
        """filter(Q1, Q2) — both as positional args."""
        results = AuthorClient.objects.filter(
            Q(age__gte=25), Q(is_active=True)
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            age__gte=25, is_active=True
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_q_arg_plus_kwargs(self):
        """filter(Q1, kwarg=val) — mixed positional Q and keyword."""
        results = AuthorClient.objects.filter(
            Q(age__gte=25), rating__gte=4.0
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            age__gte=25, rating__gte=4.0
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_or_q_arg_plus_kwargs(self):
        """filter(Q1 | Q2, kwarg=val) — OR Q with additional kwarg."""
        results = AuthorClient.objects.filter(
            Q(name="mq_a") | Q(name="mq_c"), age__gte=30
        ).order_by("id").fetch()
        # In StateZero, this creates separate filter nodes for (Q1|Q2) and Q(age>=30)
        # which is equivalent to Django's chained .filter(Q1|Q2).filter(age>=30)
        orm = (
            Author.objects
            .filter(DjangoQ(name="mq_a") | DjangoQ(name="mq_c"))
            .filter(age__gte=30)
            .order_by("id")
        )
        self.assert_ordered_pks(results, orm)


# ===========================================================================
# JSON field queries in Q
# ===========================================================================

class TestJSONFieldQParity(ExoticQueryBase):

    def setUp(self):
        super().setUp()
        Author.objects.create(name="json_a", metadata={"genre": "fiction", "level": 1})
        Author.objects.create(name="json_b", metadata={"genre": "science", "level": 2})
        Author.objects.create(name="json_c", metadata={"genre": "fiction", "level": 3})
        Author.objects.create(name="json_d", metadata={})

    def test_json_path_in_q_or(self):
        """JSON path lookup inside OR"""
        results = AuthorClient.objects.filter(
            Q(metadata__genre="fiction") | Q(metadata__level=2)
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            DjangoQ(metadata__genre="fiction") | DjangoQ(metadata__level=2)
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_json_path_in_q_and(self):
        """JSON path lookup inside AND"""
        results = AuthorClient.objects.filter(
            Q(metadata__genre="fiction") & Q(metadata__level__gte=2)
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            metadata__genre="fiction", metadata__level__gte=2
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_json_exclude(self):
        """Exclude JSON path match."""
        results = AuthorClient.objects.exclude(
            metadata__genre="fiction"
        ).order_by("id").fetch()
        orm = Author.objects.exclude(
            metadata__genre="fiction"
        ).order_by("id")
        self.assert_ordered_pks(results, orm)


# ===========================================================================
# Ordering combined with complex Q
# ===========================================================================

class TestOrderingWithQParity(ExoticQueryBase):

    def setUp(self):
        super().setUp()
        Author.objects.create(name="ord_z", age=20, rating=5.0)
        Author.objects.create(name="ord_a", age=30, rating=3.0)
        Author.objects.create(name="ord_m", age=25, rating=4.0)
        Author.objects.create(name="ord_b", age=35, rating=1.0)

    def test_order_desc_after_or_filter(self):
        results = AuthorClient.objects.filter(
            Q(age__gte=25) | Q(rating__gte=4.5)
        ).order_by("-age").fetch()
        orm = Author.objects.filter(
            DjangoQ(age__gte=25) | DjangoQ(rating__gte=4.5)
        ).order_by("-age")
        self.assert_ordered_pks(results, orm)

    def test_multi_field_order_after_complex_filter(self):
        results = (
            AuthorClient.objects
            .filter(age__gte=20)
            .exclude(rating__lt=2.0)
            .order_by("rating", "-name").fetch()
        )
        orm = (
            Author.objects
            .filter(age__gte=20)
            .exclude(rating__lt=2.0)
            .order_by("rating", "-name")
        )
        self.assert_ordered_pks(results, orm)


# ===========================================================================
# Date-part lookups in Q
# ===========================================================================

class TestDatePartQParity(ExoticQueryBase):

    def setUp(self):
        super().setUp()
        Author.objects.create(
            name="dp_jan", birth_date=date(1990, 1, 15),
            created_at=datetime(2023, 6, 15, 10, 0, tzinfo=tz.utc)
        )
        Author.objects.create(
            name="dp_jun", birth_date=date(1995, 6, 20),
            created_at=datetime(2024, 1, 10, 14, 30, tzinfo=tz.utc)
        )
        Author.objects.create(
            name="dp_dec", birth_date=date(2000, 12, 25),
            created_at=datetime(2024, 6, 1, 8, 0, tzinfo=tz.utc)
        )

    def test_year_or_month(self):
        """birth_date year=1990 OR month=12"""
        results = AuthorClient.objects.filter(
            Q(birth_date__year=1990) | Q(birth_date__month=12)
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            DjangoQ(birth_date__year=1990) | DjangoQ(birth_date__month=12)
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_datetime_year_and_month(self):
        """created_at year=2024 AND month >= 5"""
        results = AuthorClient.objects.filter(
            Q(created_at__year=2024) & Q(created_at__month__gte=5)
        ).order_by("id").fetch()
        orm = Author.objects.filter(
            created_at__year=2024, created_at__month__gte=5
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_day_with_exclude(self):
        """Filter day > 10, exclude month=1"""
        results = (
            AuthorClient.objects
            .filter(birth_date__day__gt=10)
            .exclude(birth_date__month=1)
            .order_by("id").fetch()
        )
        orm = (
            Author.objects
            .filter(birth_date__day__gt=10)
            .exclude(birth_date__month=1)
            .order_by("id")
        )
        self.assert_ordered_pks(results, orm)


# ===========================================================================
# Boolean field combinations in Q
# ===========================================================================

class TestBooleanQParity(ExoticQueryBase):

    def setUp(self):
        super().setUp()
        self.alice = Author.objects.create(name="bq_alice", age=30)
        self.bob = Author.objects.create(name="bq_bob", age=25)
        self.carol = Author.objects.create(name="bq_carol", age=35)

        Book.objects.create(title="BQ_Pub_Expensive", author=self.alice, price=Decimal("50"), is_published=True)
        Book.objects.create(title="BQ_Pub_Cheap", author=self.bob, price=Decimal("5"), is_published=True)
        Book.objects.create(title="BQ_Draft", author=self.carol, price=Decimal("30"), is_published=False)

    def test_bool_or_with_value(self):
        """published=True OR price >= 30"""
        results = BookClient.objects.filter(
            Q(is_published=True) | Q(price__gte=30)
        ).order_by("id").fetch()
        orm = Book.objects.filter(
            DjangoQ(is_published=True) | DjangoQ(price__gte=30)
        ).order_by("id")
        self.assert_ordered_pks(results, orm)

    def test_bool_and_exclude(self):
        """Published books, excluding cheap ones."""
        results = (
            BookClient.objects
            .filter(is_published=True)
            .exclude(price__lt=10)
            .order_by("id").fetch()
        )
        orm = (
            Book.objects
            .filter(is_published=True)
            .exclude(price__lt=10)
            .order_by("id")
        )
        self.assert_ordered_pks(results, orm)

    def test_bool_false_with_fk(self):
        """Unpublished by author aged >= 30"""
        results = BookClient.objects.filter(
            Q(is_published=False) & Q(author__age__gte=30)
        ).order_by("id").fetch()
        orm = Book.objects.filter(
            is_published=False, author__age__gte=30
        ).order_by("id")
        self.assert_ordered_pks(results, orm)
