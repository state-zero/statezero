# Details

Date : 2026-02-16 17:32:16

Directory /Users/robertherring/code/statezero/statezero

Total : 53 files,  7328 codes, 2638 comments, 1708 blanks, all 11674 lines

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
| [statezero/adaptors/django/config.py](/statezero/adaptors/django/config.py) | Python | 82 | 9 | 21 | 112 |
| [statezero/adaptors/django/context\_manager.py](/statezero/adaptors/django/context_manager.py) | Python | 10 | 1 | 2 | 13 |
| [statezero/adaptors/django/db\_telemetry.py](/statezero/adaptors/django/db_telemetry.py) | Python | 20 | 17 | 8 | 45 |
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
| [statezero/adaptors/django/management/commands/statezero\_testserver.py](/statezero/adaptors/django/management/commands/statezero_testserver.py) | Python | 26 | 1 | 6 | 33 |
| [statezero/adaptors/django/middleware.py](/statezero/adaptors/django/middleware.py) | Python | 8 | 4 | 5 | 17 |
| [statezero/adaptors/django/migrations/0001\_initial.py](/statezero/adaptors/django/migrations/0001_initial.py) | Python | 26 | 1 | 7 | 34 |
| [statezero/adaptors/django/migrations/0002\_delete\_modelviewsubscription.py](/statezero/adaptors/django/migrations/0002_delete_modelviewsubscription.py) | Python | 10 | 1 | 6 | 17 |
| [statezero/adaptors/django/migrations/\_\_init\_\_.py](/statezero/adaptors/django/migrations/__init__.py) | Python | 0 | 0 | 1 | 1 |
| [statezero/adaptors/django/orm.py](/statezero/adaptors/django/orm.py) | Python | 796 | 247 | 154 | 1,197 |
| [statezero/adaptors/django/permissions.py](/statezero/adaptors/django/permissions.py) | Python | 224 | 31 | 42 | 297 |
| [statezero/adaptors/django/query\_optimizer.py](/statezero/adaptors/django/query_optimizer.py) | Python | 473 | 248 | 89 | 810 |
| [statezero/adaptors/django/schemas.py](/statezero/adaptors/django/schemas.py) | Python | 338 | 30 | 51 | 419 |
| [statezero/adaptors/django/search\_providers/\_\_init\_\_.py](/statezero/adaptors/django/search_providers/__init__.py) | Python | 0 | 0 | 1 | 1 |
| [statezero/adaptors/django/search\_providers/basic\_search.py](/statezero/adaptors/django/search_providers/basic_search.py) | Python | 15 | 4 | 5 | 24 |
| [statezero/adaptors/django/search\_providers/postgres\_search.py](/statezero/adaptors/django/search_providers/postgres_search.py) | Python | 33 | 9 | 9 | 51 |
| [statezero/adaptors/django/serializers.py](/statezero/adaptors/django/serializers.py) | Python | 412 | 166 | 108 | 686 |
| [statezero/adaptors/django/signals.py](/statezero/adaptors/django/signals.py) | Python | 127 | 231 | 56 | 414 |
| [statezero/adaptors/django/testing.py](/statezero/adaptors/django/testing.py) | Python | 84 | 34 | 40 | 158 |
| [statezero/adaptors/django/urls.py](/statezero/adaptors/django/urls.py) | Python | 16 | 0 | 4 | 20 |
| [statezero/adaptors/django/utils.py](/statezero/adaptors/django/utils.py) | Python | 261 | 76 | 50 | 387 |
| [statezero/adaptors/django/views.py](/statezero/adaptors/django/views.py) | Python | 487 | 90 | 118 | 695 |
| [statezero/core/\_\_init\_\_.py](/statezero/core/__init__.py) | Python | 25 | 6 | 4 | 35 |
| [statezero/core/actions.py](/statezero/core/actions.py) | Python | 108 | 16 | 26 | 150 |
| [statezero/core/ast\_parser.py](/statezero/core/ast_parser.py) | Python | 807 | 221 | 141 | 1,169 |
| [statezero/core/ast\_validator.py](/statezero/core/ast_validator.py) | Python | 185 | 87 | 39 | 311 |
| [statezero/core/classes.py](/statezero/core/classes.py) | Python | 214 | 154 | 70 | 438 |
| [statezero/core/config.py](/statezero/core/config.py) | Python | 222 | 106 | 57 | 385 |
| [statezero/core/context\_storage.py](/statezero/core/context_storage.py) | Python | 4 | 2 | 3 | 9 |
| [statezero/core/event\_bus.py](/statezero/core/event_bus.py) | Python | 154 | 58 | 29 | 241 |
| [statezero/core/event\_emitters.py](/statezero/core/event_emitters.py) | Python | 47 | 0 | 14 | 61 |
| [statezero/core/exceptions.py](/statezero/core/exceptions.py) | Python | 67 | 8 | 32 | 107 |
| [statezero/core/hook\_checks.py](/statezero/core/hook_checks.py) | Python | 64 | 8 | 14 | 86 |
| [statezero/core/interfaces.py](/statezero/core/interfaces.py) | Python | 352 | 296 | 80 | 728 |
| [statezero/core/process\_request.py](/statezero/core/process_request.py) | Python | 238 | 50 | 51 | 339 |
| [statezero/core/query\_cache.py](/statezero/core/query_cache.py) | Python | 108 | 103 | 54 | 265 |
| [statezero/core/telemetry.py](/statezero/core/telemetry.py) | Python | 143 | 36 | 31 | 210 |
| [statezero/core/types.py](/statezero/core/types.py) | Python | 23 | 3 | 5 | 31 |

[Summary](results.md) / Details / [Diff Summary](diff.md) / [Diff Details](diff-details.md)