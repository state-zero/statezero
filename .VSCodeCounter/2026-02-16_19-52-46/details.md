# Details

Date : 2026-02-16 19:52:46

Directory /Users/robertherring/code/statezero/statezero

Total : 56 files,  6891 codes, 2345 comments, 1681 blanks, all 10917 lines

[Summary](results.md) / Details / [Diff Summary](diff.md) / [Diff Details](diff-details.md)

## Files
| filename | language | code | comment | blank | total |
| :--- | :--- | ---: | ---: | ---: | ---: |
| [statezero/\_\_init\_\_.py](/statezero/__init__.py) | Python | 0 | 0 | 1 | 1 |
| [statezero/adaptors/\_\_init\_\_.py](/statezero/adaptors/__init__.py) | Python | 0 | 0 | 1 | 1 |
| [statezero/adaptors/django/\_\_init\_\_.py](/statezero/adaptors/django/__init__.py) | Python | 0 | 0 | 1 | 1 |
| [statezero/adaptors/django/action\_serializers.py](/statezero/adaptors/django/action_serializers.py) | Python | 219 | 13 | 58 | 290 |
| [statezero/adaptors/django/actions.py](/statezero/adaptors/django/actions.py) | Python | 210 | 15 | 34 | 259 |
| [statezero/adaptors/django/apps.py](/statezero/adaptors/django/apps.py) | Python | 107 | 12 | 18 | 137 |
| [statezero/adaptors/django/ast\_parser.py](/statezero/adaptors/django/ast_parser.py) | Python | 743 | 144 | 142 | 1,029 |
| [statezero/adaptors/django/config.py](/statezero/adaptors/django/config.py) | Python | 82 | 9 | 21 | 112 |
| [statezero/adaptors/django/context\_manager.py](/statezero/adaptors/django/context_manager.py) | Python | 10 | 1 | 2 | 13 |
| [statezero/adaptors/django/db\_telemetry.py](/statezero/adaptors/django/db_telemetry.py) | Python | 20 | 17 | 8 | 45 |
| [statezero/adaptors/django/event\_bus.py](/statezero/adaptors/django/event_bus.py) | Python | 154 | 58 | 29 | 241 |
| [statezero/adaptors/django/event\_emitters.py](/statezero/adaptors/django/event_emitters.py) | Python | 64 | 0 | 14 | 78 |
| [statezero/adaptors/django/exception\_handler.py](/statezero/adaptors/django/exception_handler.py) | Python | 69 | 13 | 17 | 99 |
| [statezero/adaptors/django/extensions/\_\_init\_\_.py](/statezero/adaptors/django/extensions/__init__.py) | Python | 0 | 0 | 1 | 1 |
| [statezero/adaptors/django/extensions/custom\_field\_serializers/\_\_init\_\_.py](/statezero/adaptors/django/extensions/custom_field_serializers/__init__.py) | Python | 0 | 0 | 1 | 1 |
| [statezero/adaptors/django/extensions/custom\_field\_serializers/file\_fields.py](/statezero/adaptors/django/extensions/custom_field_serializers/file_fields.py) | Python | 106 | 9 | 27 | 142 |
| [statezero/adaptors/django/extensions/custom\_field\_serializers/money\_field.py](/statezero/adaptors/django/extensions/custom_field_serializers/money_field.py) | Python | 71 | 10 | 13 | 94 |
| [statezero/adaptors/django/extensions/custom\_field\_serializers/pydantic\_field.py](/statezero/adaptors/django/extensions/custom_field_serializers/pydantic_field.py) | Python | 24 | 19 | 11 | 54 |
| [statezero/adaptors/django/extensions/simple\_history.py](/statezero/adaptors/django/extensions/simple_history.py) | Python | 17 | 32 | 6 | 55 |
| [statezero/adaptors/django/f\_handler.py](/statezero/adaptors/django/f_handler.py) | Python | 158 | 105 | 49 | 312 |
| [statezero/adaptors/django/helpers.py](/statezero/adaptors/django/helpers.py) | Python | 74 | 56 | 23 | 153 |
| [statezero/adaptors/django/hook\_checks.py](/statezero/adaptors/django/hook_checks.py) | Python | 64 | 8 | 14 | 86 |
| [statezero/adaptors/django/management/commands/statezero\_testserver.py](/statezero/adaptors/django/management/commands/statezero_testserver.py) | Python | 26 | 1 | 6 | 33 |
| [statezero/adaptors/django/middleware.py](/statezero/adaptors/django/middleware.py) | Python | 8 | 4 | 5 | 17 |
| [statezero/adaptors/django/migrations/0001\_initial.py](/statezero/adaptors/django/migrations/0001_initial.py) | Python | 26 | 1 | 7 | 34 |
| [statezero/adaptors/django/migrations/0002\_delete\_modelviewsubscription.py](/statezero/adaptors/django/migrations/0002_delete_modelviewsubscription.py) | Python | 10 | 1 | 6 | 17 |
| [statezero/adaptors/django/migrations/\_\_init\_\_.py](/statezero/adaptors/django/migrations/__init__.py) | Python | 0 | 0 | 1 | 1 |
| [statezero/adaptors/django/orm.py](/statezero/adaptors/django/orm.py) | Python | 361 | 94 | 78 | 533 |
| [statezero/adaptors/django/permission\_bound.py](/statezero/adaptors/django/permission_bound.py) | Python | 291 | 41 | 80 | 412 |
| [statezero/adaptors/django/permission\_resolver.py](/statezero/adaptors/django/permission_resolver.py) | Python | 81 | 28 | 22 | 131 |
| [statezero/adaptors/django/permission\_utils.py](/statezero/adaptors/django/permission_utils.py) | Python | 108 | 73 | 23 | 204 |
| [statezero/adaptors/django/permissions.py](/statezero/adaptors/django/permissions.py) | Python | 224 | 31 | 42 | 297 |
| [statezero/adaptors/django/process\_request.py](/statezero/adaptors/django/process_request.py) | Python | 166 | 27 | 37 | 230 |
| [statezero/adaptors/django/query\_cache.py](/statezero/adaptors/django/query_cache.py) | Python | 108 | 103 | 54 | 265 |
| [statezero/adaptors/django/query\_optimizer.py](/statezero/adaptors/django/query_optimizer.py) | Python | 473 | 248 | 89 | 810 |
| [statezero/adaptors/django/schemas.py](/statezero/adaptors/django/schemas.py) | Python | 338 | 30 | 51 | 419 |
| [statezero/adaptors/django/search\_providers/\_\_init\_\_.py](/statezero/adaptors/django/search_providers/__init__.py) | Python | 0 | 0 | 1 | 1 |
| [statezero/adaptors/django/search\_providers/basic\_search.py](/statezero/adaptors/django/search_providers/basic_search.py) | Python | 15 | 4 | 5 | 24 |
| [statezero/adaptors/django/search\_providers/postgres\_search.py](/statezero/adaptors/django/search_providers/postgres_search.py) | Python | 33 | 9 | 9 | 51 |
| [statezero/adaptors/django/serializers.py](/statezero/adaptors/django/serializers.py) | Python | 412 | 166 | 108 | 686 |
| [statezero/adaptors/django/signals.py](/statezero/adaptors/django/signals.py) | Python | 127 | 231 | 56 | 414 |
| [statezero/adaptors/django/testing.py](/statezero/adaptors/django/testing.py) | Python | 84 | 34 | 40 | 158 |
| [statezero/adaptors/django/types.py](/statezero/adaptors/django/types.py) | Python | 8 | 1 | 2 | 11 |
| [statezero/adaptors/django/urls.py](/statezero/adaptors/django/urls.py) | Python | 16 | 0 | 4 | 20 |
| [statezero/adaptors/django/utils.py](/statezero/adaptors/django/utils.py) | Python | 261 | 76 | 50 | 387 |
| [statezero/adaptors/django/views.py](/statezero/adaptors/django/views.py) | Python | 454 | 79 | 113 | 646 |
| [statezero/core/\_\_init\_\_.py](/statezero/core/__init__.py) | Python | 25 | 6 | 4 | 35 |
| [statezero/core/actions.py](/statezero/core/actions.py) | Python | 108 | 16 | 26 | 150 |
| [statezero/core/classes.py](/statezero/core/classes.py) | Python | 202 | 154 | 66 | 422 |
| [statezero/core/config.py](/statezero/core/config.py) | Python | 239 | 102 | 62 | 403 |
| [statezero/core/context\_storage.py](/statezero/core/context_storage.py) | Python | 4 | 2 | 3 | 9 |
| [statezero/core/event\_emitters.py](/statezero/core/event_emitters.py) | Python | 47 | 0 | 14 | 61 |
| [statezero/core/exceptions.py](/statezero/core/exceptions.py) | Python | 67 | 8 | 32 | 107 |
| [statezero/core/interfaces.py](/statezero/core/interfaces.py) | Python | 221 | 216 | 57 | 494 |
| [statezero/core/telemetry.py](/statezero/core/telemetry.py) | Python | 143 | 36 | 31 | 210 |
| [statezero/core/types.py](/statezero/core/types.py) | Python | 13 | 2 | 6 | 21 |

[Summary](results.md) / Details / [Diff Summary](diff.md) / [Diff Details](diff-details.md)