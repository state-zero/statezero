# Generated by Django 5.1.6 on 2025-03-26 16:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('django_app', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='custompkmodel',
            name='custom_pk',
            field=models.IntegerField(blank=True, primary_key=True, serialize=False),
        ),
    ]
