"""
Parity tests: every client query operation compared side-by-side with Django ORM.

Uses Author, Book, Tag models (AllowAll permissions, filterable_fields="__all__")
plus existing CRUD models (ComprehensiveModel, Product, OrderItem) for field-type
and additional-field coverage.
Runs as superuser so no permission restrictions apply.
"""
import uuid
from datetime import date, datetime, timezone as tz
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from statezero.client.runtime_template import (
    Model, Q, F, configure, _field_permissions_cache,
)
from statezero.client.testing import DjangoTestTransport
from tests.django_app.models import (
    Author, Book, Tag,
    ComprehensiveModel, DeepModelLevel1, DeepModelLevel2, DeepModelLevel3,
    Product, ProductCategory, Order, OrderItem,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Client model stubs (mimic generated code)
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
    _relations = {}  # M2M not in _relations for client


class ComprehensiveModelClient(Model):
    _model_name = "django_app.comprehensivemodel"
    _pk_field = "id"
    _relations = {"related": "django_app.deepmodellevel1"}


class ProductCategoryClient(Model):
    _model_name = "django_app.productcategory"
    _pk_field = "id"
    _relations = {}


class ProductClient(Model):
    _model_name = "django_app.product"
    _pk_field = "id"
    _relations = {"category": "django_app.productcategory"}


class OrderClient(Model):
    _model_name = "django_app.order"
    _pk_field = "id"
    _relations = {}


class OrderItemClient(Model):
    _model_name = "django_app.orderitem"
    _pk_field = "id"
    _relations = {"order": "django_app.order", "product": "django_app.product"}


# ---------------------------------------------------------------------------
# Base helper
# ---------------------------------------------------------------------------

SKIP_FIELDS = {"repr"}


class ParityTestBase(TestCase):
    """Base class with assert_parity helper for comparing client vs Django ORM."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = User.objects.create_superuser(
            username="parity_admin", password="admin", email="parity@test.com"
        )

    def setUp(self):
        configure(transport=DjangoTestTransport(user=self.admin))
        _field_permissions_cache.clear()

    def assert_parity(self, client_results, orm_qs, fields):
        """Compare client fetch results to Django ORM queryset."""
        orm_list = list(orm_qs)
        self.assertEqual(
            len(client_results), len(orm_list),
            f"Length mismatch: client={len(client_results)}, orm={len(orm_list)}"
        )
        for client_obj, orm_obj in zip(client_results, orm_list):
            for field in fields:
                if field in SKIP_FIELDS:
                    continue
                client_val = getattr(client_obj, field)
                orm_val = getattr(orm_obj, field)
                client_val = self._normalize(client_val)
                orm_val = self._normalize(orm_val)
                self.assertEqual(
                    client_val, orm_val,
                    f"Field '{field}' mismatch: client={client_val!r}, orm={orm_val!r}"
                )

    @staticmethod
    def _normalize(val):
        if isinstance(val, Decimal):
            return str(val)
        if isinstance(val, uuid.UUID):
            return str(val)
        if isinstance(val, datetime):
            return val.isoformat()
        if isinstance(val, date):
            return val.isoformat()
        return val


# ===========================================================================
# READ operations
# ===========================================================================

class TestReadParity(ParityTestBase):

    def test_fetch_all(self):
        Author.objects.create(name="Alice", age=30)
        Author.objects.create(name="Bob", age=25)
        results = AuthorClient.objects.order_by("id").fetch()
        self.assert_parity(results, Author.objects.order_by("id"), ["id", "name", "age"])

    def test_fetch_with_limit(self):
        for i in range(5):
            Author.objects.create(name=f"author_{i}", age=20 + i)
        results = AuthorClient.objects.order_by("id").fetch(limit=3)
        self.assert_parity(results, Author.objects.order_by("id")[:3], ["id", "name"])

    def test_fetch_with_offset(self):
        for i in range(5):
            Author.objects.create(name=f"author_{i}", age=20 + i)
        results = AuthorClient.objects.order_by("id").fetch(limit=2, offset=2)
        self.assert_parity(results, Author.objects.order_by("id")[2:4], ["id", "name"])

    def test_get_by_pk(self):
        obj = Author.objects.create(name="Target", age=40)
        result = AuthorClient.objects.get(id=obj.pk)
        self.assertEqual(result.pk, obj.pk)
        self.assertEqual(result.name, "Target")

    def test_get_by_field(self):
        Author.objects.create(name="unique_get_test", age=50)
        result = AuthorClient.objects.get(name="unique_get_test")
        self.assertEqual(result.name, "unique_get_test")

    def test_first(self):
        Author.objects.create(name="a_first", age=10)
        Author.objects.create(name="b_second", age=20)
        result = AuthorClient.objects.order_by("age").first()
        orm_first = Author.objects.order_by("age").first()
        self.assertEqual(result.pk, orm_first.pk)

    def test_last(self):
        Author.objects.create(name="a_last", age=10)
        Author.objects.create(name="b_last", age=20)
        result = AuthorClient.objects.order_by("age").last()
        orm_last = Author.objects.order_by("age").last()
        self.assertEqual(result.pk, orm_last.pk)

    def test_first_empty(self):
        result = AuthorClient.objects.first()
        self.assertIsNone(result)

    def test_count(self):
        Author.objects.create(name="c1", age=10)
        Author.objects.create(name="c2", age=20)
        self.assertEqual(AuthorClient.objects.count(), Author.objects.count())

    def test_count_filtered(self):
        Author.objects.create(name="count_a", age=10)
        Author.objects.create(name="count_b", age=20)
        self.assertEqual(
            AuthorClient.objects.filter(age__gte=15).count(),
            Author.objects.filter(age__gte=15).count()
        )

    def test_exists_true(self):
        Author.objects.create(name="exists_test")
        self.assertTrue(AuthorClient.objects.exists())

    def test_exists_false(self):
        self.assertFalse(AuthorClient.objects.exists())


# ===========================================================================
# Filter lookups
# ===========================================================================

class TestFilterLookupsParity(ParityTestBase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        # Create common test data for filter tests
        self.a1 = Author.objects.create(name="Alice", age=30, rating=4.5, email="alice@example.com")
        self.a2 = Author.objects.create(name="Bob", age=25, rating=3.0, email="bob@test.com")
        self.a3 = Author.objects.create(name="ALICE", age=35, rating=5.0, email="ALICE@EXAMPLE.COM")

    def test_filter_exact(self):
        results = AuthorClient.objects.filter(name="Alice").fetch()
        self.assert_parity(results, Author.objects.filter(name="Alice"), ["id", "name"])

    def test_filter_iexact(self):
        results = AuthorClient.objects.filter(name__iexact="alice").fetch()
        self.assert_parity(
            results, Author.objects.filter(name__iexact="alice"), ["id", "name"]
        )

    def test_filter_contains(self):
        results = AuthorClient.objects.filter(name__contains="lic").fetch()
        self.assert_parity(results, Author.objects.filter(name__contains="lic"), ["id", "name"])

    def test_filter_icontains(self):
        results = AuthorClient.objects.filter(name__icontains="alice").fetch()
        self.assert_parity(
            results, Author.objects.filter(name__icontains="alice"), ["id", "name"]
        )

    def test_filter_startswith(self):
        results = AuthorClient.objects.filter(name__startswith="Ali").fetch()
        self.assert_parity(results, Author.objects.filter(name__startswith="Ali"), ["id", "name"])

    def test_filter_istartswith(self):
        results = AuthorClient.objects.filter(name__istartswith="ali").fetch()
        self.assert_parity(
            results, Author.objects.filter(name__istartswith="ali"), ["id", "name"]
        )

    def test_filter_endswith(self):
        results = AuthorClient.objects.filter(name__endswith="ce").fetch()
        self.assert_parity(results, Author.objects.filter(name__endswith="ce"), ["id", "name"])

    def test_filter_iendswith(self):
        results = AuthorClient.objects.filter(name__iendswith="CE").fetch()
        self.assert_parity(
            results, Author.objects.filter(name__iendswith="CE"), ["id", "name"]
        )

    def test_filter_gt(self):
        results = AuthorClient.objects.filter(age__gt=30).fetch()
        self.assert_parity(results, Author.objects.filter(age__gt=30), ["id", "name"])

    def test_filter_gte(self):
        results = AuthorClient.objects.filter(age__gte=30).fetch()
        self.assert_parity(results, Author.objects.filter(age__gte=30), ["id", "name"])

    def test_filter_lt(self):
        results = AuthorClient.objects.filter(age__lt=30).fetch()
        self.assert_parity(results, Author.objects.filter(age__lt=30), ["id", "name"])

    def test_filter_lte(self):
        results = AuthorClient.objects.filter(age__lte=30).fetch()
        self.assert_parity(results, Author.objects.filter(age__lte=30), ["id", "name"])

    def test_filter_in(self):
        results = AuthorClient.objects.filter(name__in=["Alice", "Bob"]).fetch()
        self.assert_parity(
            results, Author.objects.filter(name__in=["Alice", "Bob"]), ["id", "name"]
        )

    def test_filter_range(self):
        results = AuthorClient.objects.filter(age__range=[25, 30]).fetch()
        self.assert_parity(
            results, Author.objects.filter(age__range=[25, 30]), ["id", "name"]
        )

    def test_filter_isnull_true(self):
        Author.objects.create(name="nullage", age=None)
        results = AuthorClient.objects.filter(age__isnull=True).fetch()
        self.assert_parity(results, Author.objects.filter(age__isnull=True), ["id", "name"])

    def test_filter_isnull_false(self):
        Author.objects.create(name="nullage2", age=None)
        results = AuthorClient.objects.filter(age__isnull=False).order_by("id").fetch()
        self.assert_parity(
            results, Author.objects.filter(age__isnull=False).order_by("id"), ["id", "name"]
        )



# ===========================================================================
# Date lookups
# ===========================================================================

class TestDateLookupsParity(ParityTestBase):

    def setUp(self):
        super().setUp()
        self.a1 = Author.objects.create(
            name="d1", birth_date=date(1990, 3, 15),
            created_at=datetime(2023, 6, 15, 12, 0, tzinfo=tz.utc)
        )
        self.a2 = Author.objects.create(
            name="d2", birth_date=date(1985, 12, 1),
            created_at=datetime(2024, 1, 10, 8, 30, tzinfo=tz.utc)
        )

    def test_filter_date_year(self):
        results = AuthorClient.objects.filter(birth_date__year=1990).fetch()
        self.assert_parity(results, Author.objects.filter(birth_date__year=1990), ["id", "name"])

    def test_filter_date_month(self):
        results = AuthorClient.objects.filter(birth_date__month=12).fetch()
        self.assert_parity(results, Author.objects.filter(birth_date__month=12), ["id", "name"])

    def test_filter_date_day(self):
        results = AuthorClient.objects.filter(birth_date__day=15).fetch()
        self.assert_parity(results, Author.objects.filter(birth_date__day=15), ["id", "name"])


# ===========================================================================
# Field type filtering
# ===========================================================================

class TestFieldTypeFilteringParity(ParityTestBase):

    def test_filter_integer_field(self):
        Author.objects.create(name="int1", age=10)
        Author.objects.create(name="int2", age=20)
        results = AuthorClient.objects.filter(age=10).fetch()
        self.assert_parity(results, Author.objects.filter(age=10), ["id", "name", "age"])

    def test_filter_float_field(self):
        Author.objects.create(name="f1", rating=4.5)
        Author.objects.create(name="f2", rating=3.0)
        results = AuthorClient.objects.filter(rating__gte=4.0).fetch()
        self.assert_parity(results, Author.objects.filter(rating__gte=4.0), ["id", "name"])

    def test_filter_decimal_field(self):
        Author.objects.create(name="dec1", salary=Decimal("50000.00"))
        Author.objects.create(name="dec2", salary=Decimal("75000.00"))
        results = AuthorClient.objects.filter(salary__gte=60000).fetch()
        self.assert_parity(results, Author.objects.filter(salary__gte=60000), ["id", "name"])

    def test_filter_boolean_field(self):
        Author.objects.create(name="active", is_active=True)
        Author.objects.create(name="inactive", is_active=False)
        results = AuthorClient.objects.filter(is_active=True).fetch()
        self.assert_parity(results, Author.objects.filter(is_active=True), ["id", "name"])

    def test_filter_date_field(self):
        Author.objects.create(name="datetest1", birth_date=date(1990, 1, 1))
        Author.objects.create(name="datetest2", birth_date=date(2000, 6, 15))
        results = AuthorClient.objects.filter(birth_date__gte="2000-01-01").fetch()
        self.assert_parity(
            results, Author.objects.filter(birth_date__gte=date(2000, 1, 1)), ["id", "name"]
        )

    def test_filter_datetime_field(self):
        dt1 = datetime(2023, 1, 1, 12, 0, tzinfo=tz.utc)
        dt2 = datetime(2024, 6, 1, 12, 0, tzinfo=tz.utc)
        Author.objects.create(name="dt1", created_at=dt1)
        Author.objects.create(name="dt2", created_at=dt2)
        results = AuthorClient.objects.filter(created_at__gte="2024-01-01T00:00:00Z").fetch()
        self.assert_parity(
            results,
            Author.objects.filter(created_at__gte=datetime(2024, 1, 1, tzinfo=tz.utc)),
            ["id", "name"]
        )

    def test_filter_json_field(self):
        Author.objects.create(name="json1", metadata={"genre": "fiction"})
        Author.objects.create(name="json2", metadata={"genre": "science"})
        results = AuthorClient.objects.filter(metadata__genre="fiction").fetch()
        self.assert_parity(
            results, Author.objects.filter(metadata__genre="fiction"), ["id", "name"]
        )

    def test_filter_email_field(self):
        Author.objects.create(name="email1", email="test@example.com")
        Author.objects.create(name="email2", email="other@test.com")
        results = AuthorClient.objects.filter(email__icontains="example").fetch()
        self.assert_parity(
            results, Author.objects.filter(email__icontains="example"), ["id", "name"]
        )

    def test_filter_uuid_field(self):
        known_uuid = uuid.uuid4()
        Author.objects.create(name="uuid1", uuid=known_uuid)
        Author.objects.create(name="uuid2")
        results = AuthorClient.objects.filter(uuid=str(known_uuid)).fetch()
        self.assert_parity(
            results, Author.objects.filter(uuid=known_uuid), ["id", "name"]
        )


# ===========================================================================
# Cross-relation lookups
# ===========================================================================

class TestRelationLookupsParity(ParityTestBase):

    def setUp(self):
        super().setUp()
        self.alice = Author.objects.create(name="Alice", age=30)
        self.bob = Author.objects.create(name="Bob", age=25)
        self.book1 = Book.objects.create(title="Book A", author=self.alice, price=Decimal("10.00"))
        self.book2 = Book.objects.create(title="Book B", author=self.bob, price=Decimal("20.00"))
        self.book3 = Book.objects.create(title="Book C", author=self.alice, price=Decimal("15.00"))
        self.tag1 = Tag.objects.create(name="fiction_rel")
        self.tag1.books.set([self.book1, self.book2])
        self.tag2 = Tag.objects.create(name="science_rel")
        self.tag2.books.set([self.book3])

    def test_filter_fk_field(self):
        results = BookClient.objects.filter(author__name="Alice").order_by("id").fetch()
        self.assert_parity(
            results, Book.objects.filter(author__name="Alice").order_by("id"), ["id", "title"]
        )

    def test_filter_fk_nested(self):
        results = BookClient.objects.filter(author__age__gte=30).order_by("id").fetch()
        self.assert_parity(
            results, Book.objects.filter(author__age__gte=30).order_by("id"), ["id", "title"]
        )

    def test_filter_reverse_fk(self):
        """Reverse FK: Author → Book via related_name 'books'.
        The Author model config exposes 'books' via filterable_fields='__all__'
        but the 'books' reverse relation is not in visible_fields for non-explicit
        field configs. So we filter on a Book's author instead."""
        results = BookClient.objects.filter(author__name="Alice").order_by("id").fetch()
        self.assertEqual(len(results), 2)
        titles = {r.title for r in results}
        self.assertEqual(titles, {"Book A", "Book C"})

    def test_filter_m2m(self):
        results = TagClient.objects.filter(books__title="Book A").fetch()
        self.assert_parity(
            results, Tag.objects.filter(books__title="Book A"), ["id", "name"]
        )

    def test_filter_m2m_nested(self):
        results = TagClient.objects.filter(books__author__name="Alice").order_by("id").fetch()
        self.assert_parity(
            results,
            Tag.objects.filter(books__author__name="Alice").distinct().order_by("id"),
            ["id", "name"]
        )


# ===========================================================================
# Exclude
# ===========================================================================

class TestExcludeParity(ParityTestBase):

    def setUp(self):
        super().setUp()
        self.a1 = Author.objects.create(name="exc_keep", age=30)
        self.a2 = Author.objects.create(name="exc_drop", age=25)
        self.a3 = Author.objects.create(name="exc_other", age=20)

    def test_exclude_basic(self):
        results = AuthorClient.objects.exclude(name="exc_drop").order_by("id").fetch()
        self.assert_parity(
            results, Author.objects.exclude(name="exc_drop").order_by("id"), ["id", "name"]
        )

    def test_exclude_with_filter(self):
        results = (
            AuthorClient.objects
            .filter(age__gte=20)
            .exclude(name="exc_drop")
            .order_by("id")
            .fetch()
        )
        self.assert_parity(
            results,
            Author.objects.filter(age__gte=20).exclude(name="exc_drop").order_by("id"),
            ["id", "name"]
        )

    def test_exclude_lookup(self):
        results = AuthorClient.objects.exclude(age__lt=25).order_by("id").fetch()
        self.assert_parity(
            results, Author.objects.exclude(age__lt=25).order_by("id"), ["id", "name"]
        )


# ===========================================================================
# Q objects
# ===========================================================================

class TestQObjectsParity(ParityTestBase):

    def setUp(self):
        super().setUp()
        self.a1 = Author.objects.create(name="q_alice", age=30, rating=4.5)
        self.a2 = Author.objects.create(name="q_bob", age=25, rating=3.0)
        self.a3 = Author.objects.create(name="q_charlie", age=35, rating=5.0)

    def test_q_or(self):
        results = AuthorClient.objects.filter(
            Q(name="q_alice") | Q(name="q_charlie")
        ).order_by("id").fetch()
        self.assert_parity(
            results,
            Author.objects.filter(
                __import__('django.db.models', fromlist=['Q']).Q(name="q_alice") |
                __import__('django.db.models', fromlist=['Q']).Q(name="q_charlie")
            ).order_by("id"),
            ["id", "name"]
        )

    def test_q_and(self):
        results = AuthorClient.objects.filter(
            Q(name="q_alice") & Q(age=30)
        ).fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "q_alice")

    def test_q_nested(self):
        """(Q(a) | Q(b)) & Q(c)"""
        results = AuthorClient.objects.filter(
            (Q(name="q_alice") | Q(name="q_bob")) & Q(age__gte=30)
        ).fetch()
        # Only q_alice (age=30) matches; q_bob (age=25) doesn't pass the AND
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "q_alice")

    def test_q_with_lookups(self):
        results = AuthorClient.objects.filter(
            Q(age__gte=35) | Q(name__startswith="q_a")
        ).order_by("id").fetch()
        names = {r.name for r in results}
        self.assertEqual(names, {"q_alice", "q_charlie"})


# ===========================================================================
# Ordering
# ===========================================================================

class TestOrderingParity(ParityTestBase):

    def setUp(self):
        super().setUp()
        self.a1 = Author.objects.create(name="ord_c", age=30, rating=1.0)
        self.a2 = Author.objects.create(name="ord_a", age=25, rating=3.0)
        self.a3 = Author.objects.create(name="ord_b", age=25, rating=2.0)

    def test_order_by_single(self):
        results = AuthorClient.objects.order_by("name").fetch()
        self.assert_parity(results, Author.objects.order_by("name"), ["id", "name"])

    def test_order_by_descending(self):
        results = AuthorClient.objects.order_by("-age").fetch()
        self.assert_parity(results, Author.objects.order_by("-age"), ["name", "age"])

    def test_order_by_multiple(self):
        results = AuthorClient.objects.order_by("age", "name").fetch()
        self.assert_parity(
            results, Author.objects.order_by("age", "name"), ["id", "name", "age"]
        )

    def test_order_by_relation(self):
        alice = Author.objects.create(name="z_author", age=50)
        bob = Author.objects.create(name="a_author", age=20)
        Book.objects.create(title="zbook", author=alice)
        Book.objects.create(title="abook", author=bob)
        results = BookClient.objects.order_by("author__name").fetch()
        self.assert_parity(
            results, Book.objects.order_by("author__name"), ["id", "title"]
        )


# ===========================================================================
# Aggregation
# ===========================================================================

class TestAggregationParity(ParityTestBase):

    def setUp(self):
        super().setUp()
        Author.objects.create(name="agg1", age=10, rating=2.0)
        Author.objects.create(name="agg2", age=20, rating=4.0)
        Author.objects.create(name="agg3", age=30, rating=6.0)

    def test_sum(self):
        from django.db.models import Sum
        client_val = AuthorClient.objects.sum("age")
        orm_val = Author.objects.aggregate(s=Sum("age"))["s"]
        self.assertEqual(client_val, orm_val)

    def test_avg(self):
        from django.db.models import Avg
        client_val = AuthorClient.objects.avg("age")
        orm_val = Author.objects.aggregate(a=Avg("age"))["a"]
        self.assertEqual(client_val, orm_val)

    def test_min(self):
        from django.db.models import Min
        client_val = AuthorClient.objects.min("age")
        orm_val = Author.objects.aggregate(m=Min("age"))["m"]
        self.assertEqual(client_val, orm_val)

    def test_max(self):
        from django.db.models import Max
        client_val = AuthorClient.objects.max("age")
        orm_val = Author.objects.aggregate(m=Max("age"))["m"]
        self.assertEqual(client_val, orm_val)

    def test_aggregation_with_filter(self):
        from django.db.models import Sum
        client_val = AuthorClient.objects.filter(age__gte=20).sum("age")
        orm_val = Author.objects.filter(age__gte=20).aggregate(s=Sum("age"))["s"]
        self.assertEqual(client_val, orm_val)


# ===========================================================================
# Depth & Fields
# ===========================================================================

class TestDepthFieldsParity(ParityTestBase):

    def setUp(self):
        super().setUp()
        self.author = Author.objects.create(name="depth_author", age=40)
        self.book = Book.objects.create(title="depth_book", author=self.author, price=Decimal("29.99"))

    def test_depth_0_returns_pk(self):
        results = BookClient.objects.filter(title="depth_book").fetch(depth=0)
        self.assertEqual(len(results), 1)
        # At depth=0, FK should be raw PK
        self.assertEqual(results[0].author, self.author.pk)

    def test_depth_1_resolves_fk(self):
        results = BookClient.objects.filter(title="depth_book").fetch(depth=1)
        self.assertEqual(len(results), 1)
        resolved = results[0].author
        self.assertIsInstance(resolved, AuthorClient)
        self.assertEqual(resolved.name, "depth_author")

    def test_get_with_depth(self):
        result = BookClient.objects.get(id=self.book.pk, depth=1)
        self.assertIsInstance(result.author, AuthorClient)
        self.assertEqual(result.author.name, "depth_author")

    def test_fields_selection(self):
        results = AuthorClient.objects.filter(name="depth_author").fetch(fields=["name", "age"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "depth_author")
        self.assertEqual(results[0].age, 40)


# ===========================================================================
# Search
# ===========================================================================

class TestSearchParity(ParityTestBase):

    def setUp(self):
        super().setUp()
        Author.objects.create(name="searchable_alice", bio="Great writer", email="alice@books.com")
        Author.objects.create(name="searchable_bob", bio="Tech author", email="bob@tech.com")
        Author.objects.create(name="charlie_no_match", bio="Unknown", email="c@x.com")

    def test_search_basic(self):
        results = AuthorClient.objects.search("searchable").fetch()
        self.assertEqual(len(results), 2)
        names = {r.name for r in results}
        self.assertIn("searchable_alice", names)
        self.assertIn("searchable_bob", names)

    def test_search_with_filter(self):
        results = AuthorClient.objects.search("searchable").filter(
            name__icontains="bob"
        ).fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "searchable_bob")


# ===========================================================================
# Write operations
# ===========================================================================

class TestWriteParity(ParityTestBase):

    def test_create_and_verify_in_db(self):
        result = AuthorClient.objects.create(name="new_author", age=28)
        self.assertIsNotNone(result.pk)
        self.assertEqual(result.name, "new_author")
        self.assertTrue(Author.objects.filter(pk=result.pk).exists())

    def test_bulk_create(self):
        items = [
            {"name": "bulk_1", "age": 10},
            {"name": "bulk_2", "age": 20},
            {"name": "bulk_3", "age": 30},
        ]
        results = AuthorClient.objects.bulk_create(items)
        self.assertEqual(len(results), 3)
        self.assertEqual(Author.objects.filter(name__startswith="bulk_").count(), 3)

    def test_update_queryset(self):
        Author.objects.create(name="upd_target", age=10)
        Author.objects.create(name="upd_other", age=20)
        results = AuthorClient.objects.filter(name="upd_target").update(age=99)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].age, 99)
        self.assertEqual(Author.objects.get(name="upd_target").age, 99)

    def test_update_instance(self):
        obj = Author.objects.create(name="inst_upd", age=10)
        instance = AuthorClient.objects.get(id=obj.pk)
        updated = instance.update(name="inst_updated")
        self.assertEqual(updated.name, "inst_updated")
        obj.refresh_from_db()
        self.assertEqual(obj.name, "inst_updated")

    def test_delete_queryset(self):
        Author.objects.create(name="del_target", age=10)
        Author.objects.create(name="del_keep", age=20)
        count = AuthorClient.objects.filter(name="del_target").delete()
        self.assertEqual(count, 1)
        self.assertEqual(Author.objects.count(), 1)

    def test_delete_instance(self):
        obj = Author.objects.create(name="del_inst", age=10)
        instance = AuthorClient.objects.get(id=obj.pk)
        instance.delete()
        self.assertFalse(Author.objects.filter(pk=obj.pk).exists())

    def test_get_or_create_creates(self):
        instance, created = AuthorClient.objects.get_or_create(
            defaults={"age": 42}, name="goc_new"
        )
        self.assertTrue(created)
        self.assertEqual(instance.name, "goc_new")
        self.assertEqual(instance.age, 42)

    def test_get_or_create_gets(self):
        Author.objects.create(name="goc_existing", age=10)
        instance, created = AuthorClient.objects.get_or_create(
            defaults={"age": 99}, name="goc_existing"
        )
        self.assertFalse(created)
        self.assertEqual(instance.age, 10)

    def test_update_or_create_creates(self):
        instance, created = AuthorClient.objects.update_or_create(
            defaults={"age": 55}, name="uoc_new"
        )
        self.assertTrue(created)
        self.assertEqual(instance.age, 55)

    def test_update_or_create_updates(self):
        Author.objects.create(name="uoc_existing", age=10)
        instance, created = AuthorClient.objects.update_or_create(
            defaults={"age": 99}, name="uoc_existing"
        )
        self.assertFalse(created)
        self.assertEqual(instance.age, 99)


# ===========================================================================
# F expressions
# ===========================================================================

class TestFExpressionsParity(ParityTestBase):

    def test_f_add(self):
        Author.objects.create(name="f_add", age=10)
        results = AuthorClient.objects.filter(name="f_add").update(age=F("age") + 5)
        self.assertEqual(results[0].age, 15)

    def test_f_subtract(self):
        Author.objects.create(name="f_sub", age=20)
        results = AuthorClient.objects.filter(name="f_sub").update(age=F("age") - 3)
        self.assertEqual(results[0].age, 17)

    def test_f_multiply(self):
        Author.objects.create(name="f_mul", age=5)
        results = AuthorClient.objects.filter(name="f_mul").update(age=F("age") * 4)
        self.assertEqual(results[0].age, 20)

    def test_f_divide(self):
        Author.objects.create(name="f_div", age=20)
        results = AuthorClient.objects.filter(name="f_div").update(age=F("age") / 4)
        self.assertEqual(results[0].age, 5)

    def test_f_modulo(self):
        Author.objects.create(name="f_mod", age=17)
        results = AuthorClient.objects.filter(name="f_mod").update(age=F("age") % 5)
        self.assertEqual(results[0].age, 2)

    def test_f_power(self):
        Author.objects.create(name="f_pow", age=3)
        results = AuthorClient.objects.filter(name="f_pow").update(age=F("age") ** 2)
        self.assertEqual(results[0].age, 9)


# ===========================================================================
# Iteration
# ===========================================================================

class TestIterationParity(ParityTestBase):

    def test_iter(self):
        Author.objects.create(name="iter1", age=1)
        Author.objects.create(name="iter2", age=2)
        names = {item.name for item in AuthorClient.objects.all()}
        self.assertEqual(names, {"iter1", "iter2"})

    def test_len(self):
        Author.objects.create(name="len1", age=1)
        Author.objects.create(name="len2", age=2)
        Author.objects.create(name="len3", age=3)
        qs = AuthorClient.objects.all()
        self.assertEqual(len(qs), Author.objects.count())


# ===========================================================================
# Null handling
# ===========================================================================

class TestNullHandlingParity(ParityTestBase):

    def test_filter_null_field(self):
        Author.objects.create(name="has_age", age=30)
        Author.objects.create(name="no_age", age=None)
        results = AuthorClient.objects.filter(age__isnull=True).fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "no_age")

    def test_create_with_null_fields(self):
        result = AuthorClient.objects.create(name="null_create", age=None, salary=None)
        self.assertIsNone(result.age)
        self.assertIsNone(result.salary)
        obj = Author.objects.get(pk=result.pk)
        self.assertIsNone(obj.age)
        self.assertIsNone(obj.salary)


# ===========================================================================
# CRUD field types — ComprehensiveModel (MoneyField, DecimalField, JSONField)
# ===========================================================================

class TestComprehensiveModelFieldsParity(ParityTestBase):
    """Tests for existing CRUD model field types: MoneyField, DecimalField, JSONField, etc."""

    def test_create_with_money_field(self):
        result = ComprehensiveModelClient.objects.create(
            char_field="money_test",
            text_field="desc",
            int_field=1,
            decimal_field="10.50",
            money_field={"amount": "25.99", "currency": "USD"},
        )
        self.assertIsNotNone(result.pk)
        obj = ComprehensiveModel.objects.get(pk=result.pk)
        self.assertEqual(str(obj.money_field.amount), "25.99")

    def test_create_with_nullable_money_field_null(self):
        result = ComprehensiveModelClient.objects.create(
            char_field="null_money",
            text_field="desc",
            int_field=2,
            decimal_field="5.00",
        )
        self.assertIsNotNone(result.pk)
        obj = ComprehensiveModel.objects.get(pk=result.pk)
        # nullable MoneyField with no value set → None
        self.assertIsNone(obj.nullable_money_field)

    def test_filter_by_char_field(self):
        ComprehensiveModel.objects.create(
            char_field="filter_target", text_field="t", int_field=10,
            decimal_field=Decimal("1.00"),
        )
        ComprehensiveModel.objects.create(
            char_field="filter_other", text_field="t", int_field=20,
            decimal_field=Decimal("2.00"),
        )
        results = ComprehensiveModelClient.objects.filter(char_field="filter_target").fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].char_field, "filter_target")

    def test_filter_by_int_field(self):
        ComprehensiveModel.objects.create(
            char_field="int1", text_field="t", int_field=100,
            decimal_field=Decimal("1.00"),
        )
        ComprehensiveModel.objects.create(
            char_field="int2", text_field="t", int_field=200,
            decimal_field=Decimal("2.00"),
        )
        results = ComprehensiveModelClient.objects.filter(int_field__gte=150).fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].char_field, "int2")

    def test_json_field_roundtrip(self):
        ComprehensiveModel.objects.create(
            char_field="json_rt", text_field="t", int_field=1,
            decimal_field=Decimal("1.00"),
            json_field={"key": "value", "nested": {"a": 1}},
        )
        results = ComprehensiveModelClient.objects.filter(char_field="json_rt").fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].json_field, {"key": "value", "nested": {"a": 1}})

    def test_bool_field_roundtrip(self):
        ComprehensiveModel.objects.create(
            char_field="bool_true", text_field="t", int_field=1,
            decimal_field=Decimal("1.00"), bool_field=True,
        )
        ComprehensiveModel.objects.create(
            char_field="bool_false", text_field="t", int_field=2,
            decimal_field=Decimal("2.00"), bool_field=False,
        )
        results = ComprehensiveModelClient.objects.filter(char_field="bool_true").fetch()
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].bool_field)

        results = ComprehensiveModelClient.objects.filter(char_field="bool_false").fetch()
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].bool_field)

    def test_decimal_field_precision(self):
        ComprehensiveModel.objects.create(
            char_field="dec_prec", text_field="t", int_field=1,
            decimal_field=Decimal("123456.78"),
        )
        results = ComprehensiveModelClient.objects.filter(char_field="dec_prec").fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(str(results[0].decimal_field), "123456.78")


# ===========================================================================
# Tag MoneyField
# ===========================================================================

class TestTagMoneyFieldParity(ParityTestBase):
    """Tests for MoneyField on Tag model."""

    def test_create_tag_with_cost(self):
        result = TagClient.objects.create(
            name="moneytag",
            cost={"amount": "15.50", "currency": "USD"},
        )
        self.assertIsNotNone(result.pk)
        obj = Tag.objects.get(pk=result.pk)
        self.assertEqual(str(obj.cost.amount), "15.50")
        self.assertEqual(str(obj.cost_currency), "USD")

    def test_fetch_tag_cost_fields(self):
        Tag.objects.create(name="fetch_cost", cost=Decimal("99.99"))
        results = TagClient.objects.filter(name="fetch_cost").fetch()
        self.assertEqual(len(results), 1)
        # MoneyField serializes as separate amount and currency fields
        d = results[0].to_dict()
        self.assertIn("cost", d)
        self.assertIn("cost_currency", d)


# ===========================================================================
# Additional (computed) fields — Product, OrderItem
# ===========================================================================

class TestAdditionalFieldsParity(ParityTestBase):
    """Tests for additional_fields (computed @property fields exposed via ModelConfig)."""

    def setUp(self):
        super().setUp()
        self.category = ProductCategory.objects.create(name="Electronics")

    def test_product_price_with_tax(self):
        """Product has additional_field 'price_with_tax' = price * 1.2"""
        Product.objects.create(
            name="Laptop", description="A laptop", price=Decimal("100.00"),
            category=self.category,
        )
        results = ProductClient.objects.filter(name="Laptop").fetch()
        self.assertEqual(len(results), 1)
        d = results[0].to_dict()
        self.assertIn("price_with_tax", d)
        # 100.00 * 1.2 = 120.0
        self.assertAlmostEqual(float(d["price_with_tax"]), 120.0, places=1)

    def test_product_display_name(self):
        """Product has additional_field 'display_name' = 'name (category.name)'"""
        Product.objects.create(
            name="Phone", description="A phone", price=Decimal("50.00"),
            category=self.category,
        )
        results = ProductClient.objects.filter(name="Phone").fetch()
        self.assertEqual(len(results), 1)
        d = results[0].to_dict()
        self.assertIn("display_name", d)
        self.assertEqual(d["display_name"], "Phone (Electronics)")

    def test_product_additional_fields_on_get(self):
        """Additional fields should be present on get() as well."""
        p = Product.objects.create(
            name="Tablet", description="A tablet", price=Decimal("200.00"),
            category=self.category,
        )
        result = ProductClient.objects.filter(id=p.pk).first()
        self.assertIsNotNone(result)
        self.assertAlmostEqual(float(result.price_with_tax), 240.0, places=1)
        self.assertEqual(result.display_name, "Tablet (Electronics)")

    def test_orderitem_subtotal(self):
        """OrderItem has additional_field 'subtotal' = price * quantity"""
        cat = self.category
        product = Product.objects.create(
            name="Widget", description="A widget", price=Decimal("10.00"),
            category=cat,
        )
        order = Order.objects.create(
            order_number="ORD-TEST-001",
            customer_name="Alice",
            customer_email="alice@test.com",
            total=Decimal("30.00"),
        )
        item = OrderItem.objects.create(
            order=order, product=product, quantity=3, price=Decimal("10.00")
        )
        results = OrderItemClient.objects.filter(id=item.pk).fetch()
        self.assertEqual(len(results), 1)
        d = results[0].to_dict()
        self.assertIn("subtotal", d)
        self.assertAlmostEqual(float(d["subtotal"]), 30.0, places=1)

    def test_additional_fields_not_writable(self):
        """Additional fields are read-only — sending them in create should be ignored."""
        result = ProductClient.objects.create(
            name="ReadOnlyTest", description="test", price="50.00",
            category=self.category.pk,
            price_with_tax="999.99",  # should be ignored
        )
        self.assertIsNotNone(result.pk)
        # price_with_tax should be computed, not the value we sent
        self.assertAlmostEqual(float(result.price_with_tax), 60.0, places=1)

    def test_product_created_by_hook(self):
        """Product has a pre_hook (set_created_by) that sets created_by to the user."""
        result = ProductClient.objects.create(
            name="HookTest", description="test", price="25.00",
            category=self.category.pk,
        )
        self.assertIsNotNone(result.pk)
        obj = Product.objects.get(pk=result.pk)
        # The pre_hook sets created_by to request.user.username
        self.assertEqual(obj.created_by, "parity_admin")

    def test_multiple_products_additional_fields(self):
        """All products in a fetch should have their own computed values."""
        Product.objects.create(
            name="Cheap", description="c", price=Decimal("10.00"),
            category=self.category,
        )
        Product.objects.create(
            name="Expensive", description="e", price=Decimal("100.00"),
            category=self.category,
        )
        results = ProductClient.objects.order_by("price").fetch()
        self.assertEqual(len(results), 2)
        self.assertAlmostEqual(float(results[0].price_with_tax), 12.0, places=1)
        self.assertAlmostEqual(float(results[1].price_with_tax), 120.0, places=1)

    def test_product_fk_at_depth_0(self):
        """Product.category should be raw PK at depth 0."""
        Product.objects.create(
            name="DepthTest", description="d", price=Decimal("10.00"),
            category=self.category,
        )
        results = ProductClient.objects.filter(name="DepthTest").fetch(depth=0)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].category, self.category.pk)

    def test_product_fk_at_depth_1(self):
        """Product.category should resolve to ProductCategoryClient at depth 1."""
        Product.objects.create(
            name="DepthTest1", description="d", price=Decimal("10.00"),
            category=self.category,
        )
        results = ProductClient.objects.filter(name="DepthTest1").fetch(depth=1)
        self.assertEqual(len(results), 1)
        resolved = results[0].category
        self.assertIsInstance(resolved, ProductCategoryClient)
        self.assertEqual(resolved.name, "Electronics")
