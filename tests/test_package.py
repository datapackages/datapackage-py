 # -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os
import six
import sys
import glob
import json
import mock
import zipfile
import pytest
import tempfile
import httpretty
import sqlalchemy
from copy import deepcopy
from mock import Mock, ANY
from tableschema import Storage
import tableschema.exceptions
from datapackage import Package, helpers, exceptions


# General

def test_init_accepts_dicts():
    descriptor = {
        'profile': 'data-package',
    }
    package = Package(descriptor)
    assert package.descriptor == descriptor


def test_init_accepts_filelike_object():
    descriptor = {
        'profile': 'data-package',
    }
    filelike_descriptor = six.StringIO(json.dumps(descriptor))
    package = Package(filelike_descriptor)
    assert package.descriptor == descriptor


def test_init_accepts_file_paths():
    pakcage = Package('data/empty_datapackage.json')
    assert pakcage.descriptor == {
        'profile': 'data-package',
    }


def test_init_raises_if_file_path_doesnt_exist():
    path = 'this-file-doesnt-exist.json'
    with pytest.raises(exceptions.DataPackageException):
        Package(path)


def test_init_raises_if_path_isnt_a_json():
    with pytest.raises(exceptions.DataPackageException):
        Package('data/not_a_json')


def test_init_raises_if_path_is_a_bad_json():
    with pytest.raises(exceptions.DataPackageException) as excinfo:
        Package('data/bad_json.json')
    message = str(excinfo.value)
    assert 'Unable to parse JSON' in message
    assert 'line 2 column 5 (char 6)' in message


def test_init_raises_if_path_json_isnt_a_dict():
    with pytest.raises(exceptions.DataPackageException):
        Package('data/empty_array.json')


def test_init_raises_if_filelike_object_isnt_a_json():
    invalid_json = six.StringIO('{"foo"}')
    with pytest.raises(exceptions.DataPackageException):
        Package(invalid_json)


@httpretty.activate
def test_init_accepts_urls():
    url = 'http://someplace.com/datapackage.json'
    body = '{"profile": "data-package"}'
    httpretty.register_uri(httpretty.GET, url, body=body, content_type='application/json')
    pakcage = Package(url)
    assert pakcage.descriptor == {'profile': 'data-package'}


@httpretty.activate
def test_init_accepts_text_plain_urls():
    url = 'http://someplace.com/datapackage.json'
    body = '{"profile": "data-package", "title": "כותרת"}'
    httpretty.register_uri(httpretty.GET, url, body=body, content_type='text/plain')
    pakcage = Package(url)
    assert pakcage.descriptor == {'profile': 'data-package', 'title': 'כותרת'}


@httpretty.activate
def test_init_raises_if_url_doesnt_exist():
    url = 'http://someplace.com/datapackage.json'
    httpretty.register_uri(httpretty.GET, url, status=404)
    with pytest.raises(exceptions.DataPackageException):
        Package(url)


@httpretty.activate
def test_init_raises_if_url_isnt_a_json():
    url = 'http://someplace.com/datapackage.json'
    body = 'Not a JSON'
    httpretty.register_uri(httpretty.GET, url, body=body, content_type='application/json')
    with pytest.raises(exceptions.DataPackageException):
        Package(url)


@httpretty.activate
def test_init_raises_if_url_json_isnt_a_dict():
    url = 'http://someplace.com/datapackage.json'
    body = '["foo"]'
    httpretty.register_uri(httpretty.GET, url, body=body, content_type='application/json')
    with pytest.raises(exceptions.DataPackageException):
        Package(url)


def test_init_raises_if_descriptor_isnt_dict_or_string():
    descriptor = 51
    with pytest.raises(exceptions.DataPackageException):
        Package(descriptor)

@pytest.mark.skip('deprecated')
def test_to_json():
    descriptor = {
        'foo': 'bar',
    }
    package = Package(descriptor)
    assert json.loads(package.to_json()) == descriptor


def test_descriptor_dereferencing_uri():
    package = Package('data/datapackage_with_dereferencing.json')
    assert package.descriptor['resources'] == list(map(helpers.expand_resource_descriptor, [
        {'name': 'name1', 'data': 'data', 'schema': {'fields': [{'name': 'name'}]}},
        {'name': 'name2', 'data': 'data', 'dialect': {'delimiter': ','}},
    ]))


def test_descriptor_dereferencing_uri_pointer():
    descriptor = {
        'resources': [
            {'name': 'name1', 'data': 'data', 'schema': '#/schemas/main'},
            {'name': 'name2', 'data': 'data', 'dialect': '#/dialects/0'},
         ],
        'schemas': {'main': {'fields': [{'name': 'name'}]}},
        'dialects': [{'delimiter': ','}],
    }
    package = Package(descriptor)
    assert package.descriptor['resources'] == list(map(helpers.expand_resource_descriptor, [
        {'name': 'name1', 'data': 'data', 'schema': {'fields': [{'name': 'name'}]}},
        {'name': 'name2', 'data': 'data', 'dialect': {'delimiter': ','}},
    ]))


def test_descriptor_dereferencing_uri_pointer_bad():
    descriptor = {
        'resources': [
            {'name': 'name1', 'data': 'data', 'schema': '#/schemas/main'},
         ],
    }
    with pytest.raises(exceptions.DataPackageException):
        package = Package(descriptor)


@pytest.mark.skipif(six.PY2, reason='httpretty problem with https in Python 2')
@httpretty.activate
def test_descriptor_dereferencing_uri_remote():
    # Mocks
    httpretty.register_uri(httpretty.GET,
        'http://example.com/schema', body='{"fields": [{"name": "name"}]}')
    httpretty.register_uri(httpretty.GET,
        'https://example.com/dialect', body='{"delimiter": ","}')
    # Tests
    descriptor = {
        'resources': [
            {'name': 'name1', 'data': 'data', 'schema': 'http://example.com/schema'},
            {'name': 'name2', 'data': 'data', 'dialect': 'https://example.com/dialect'},
         ],
    }
    package = Package(descriptor)
    assert package.descriptor['resources'] == list(map(helpers.expand_resource_descriptor, [
        {'name': 'name1', 'data': 'data', 'schema': {'fields': [{'name': 'name'}]}},
        {'name': 'name2', 'data': 'data', 'dialect': {'delimiter': ','}},
    ]))


def test_descriptor_dereferencing_uri_remote_bad():
    # Mocks
    httpretty.register_uri(httpretty.GET, 'http://example.com/schema', status=404)
    # Tests
    descriptor = {
        'resources': [
            {'name': 'name1', 'data': 'data', 'schema': 'http://example.com/schema'},
         ],
    }
    with pytest.raises(exceptions.DataPackageException):
        package = Package(descriptor)


def test_descriptor_dereferencing_uri_local():
    descriptor = {
        'resources': [
            {'name': 'name1', 'data': 'data', 'schema': 'table_schema.json'},
            {'name': 'name2', 'data': 'data', 'dialect': 'csv_dialect.json'},
         ],
    }
    package = Package(descriptor, default_base_path='data')
    assert package.descriptor['resources'] == list(map(helpers.expand_resource_descriptor, [
        {'name': 'name1', 'data': 'data', 'schema': {'fields': [{'name': 'name'}]}},
        {'name': 'name2', 'data': 'data', 'dialect': {'delimiter': ','}},
    ]))


def test_descriptor_dereferencing_uri_local_bad():
    descriptor = {
        'resources': [
            {'name': 'name1', 'data': 'data', 'schema': 'bad_path.json'},
         ],
    }
    with pytest.raises(exceptions.DataPackageException):
        package = Package(descriptor, default_base_path='data')


def test_descriptor_dereferencing_uri_local_bad_not_safe():
    descriptor = {
        'resources': [
            {'name': 'name1', 'data': 'data', 'schema': '../data/table_schema.json'},
         ],
    }
    with pytest.raises(exceptions.DataPackageException):
        package = Package(descriptor, default_base_path='data')


def test_descriptor_apply_defaults():
    descriptor = {}
    package = Package(descriptor)
    assert package.descriptor == {
        'profile': 'data-package',
    }


def test_descriptor_apply_defaults_resource():
    descriptor = {
        'resources': [{'name': 'name', 'data': 'data'}],
    }
    package = Package(descriptor)
    assert package.descriptor == {
        'profile': 'data-package',
        'resources': [
            {'name': 'name', 'data': 'data', 'profile': 'data-resource'},
        ]
    }


def test_descriptor_apply_defaults_resource_tabular_schema():
    descriptor = {
        'resources': [{
            'name': 'name',
            'data': 'data',
            'profile': 'tabular-data-resource',
            'schema': {
                'fields': [{'name': 'name'}],
            }
        }],
    }
    package = Package(descriptor)
    assert package.descriptor == {
        'profile': 'data-package',
        'resources': [{
            'name': 'name',
            'data': 'data',
            'profile': 'tabular-data-resource',
            'schema': {
                'fields': [{'name': 'name', 'type': 'string', 'format': 'default'}],
                'missingValues': [''],
            }
        }],
    }


def test_descriptor_apply_defaults_resource_tabular_dialect():
    descriptor = {
        'resources': [{
            'name': 'name',
            'data': 'data',
            'profile': 'tabular-data-resource',
            'dialect': {
                'delimiter': 'custom',
            }
        }],
    }
    package = Package(descriptor)
    assert package.descriptor == {
        'profile': 'data-package',
        'resources': [{
            'name': 'name',
            'data': 'data',
            'profile': 'tabular-data-resource',
            'dialect': {
                'delimiter': 'custom',
                'doubleQuote': True,
                'lineTerminator': '\r\n',
                'quoteChar': '"',
                'skipInitialSpace': True,
                'header': True,
                'caseSensitiveHeader': False,
            }
        }],
    }


def test_package_add_resource():
    package = Package({})
    resource = package.add_resource({'name': 'name', 'data': []})
    assert len(package.resources) == 1
    assert package.resources[0].name == 'name'
    assert resource.name == 'name'


def test_package_remove_resource():
    package = Package({'resources': [{'name': 'name', 'data': []}]})
    resource = package.remove_resource('name')
    assert len(package.resources) == 0
    assert resource.name == 'name'


# Resources

def test_base_path_cant_be_set_directly():
    package = Package()
    with pytest.raises(AttributeError):
        package.base_path = 'foo'


@pytest.mark.skip('deprecated')
def test_base_path_is_datapackages_base_path_when_it_is_a_file():
    path = 'data/empty_datapackage.json'
    base_path = os.path.dirname(path)
    package = Package(path)
    assert package.base_path == base_path


@httpretty.activate
def test_base_path_is_set_to_base_url_when_datapackage_is_in_url():
    base_url = 'http://someplace.com/data'
    url = '{base_url}/datapackage.json'.format(base_url=base_url)
    body = '{}'
    httpretty.register_uri(httpretty.GET, url, body=body)
    package = Package(url)
    assert package.base_path == base_url


def test_resources_are_empty_list_by_default():
    descriptor = {}
    package = Package(descriptor)
    assert package.resources == []


def test_cant_assign_to_resources():
    descriptor = {}
    package = Package(descriptor)
    with pytest.raises(AttributeError):
        package.resources = ()


def test_inline_resources_are_loaded():
    descriptor = {
        'resources': [
            {'data': 'foo'},
            {'data': 'bar'},
        ],
    }
    package = Package(descriptor)
    assert len(package.resources) == 2
    assert package.resources[0].source == 'foo'
    assert package.resources[1].source == 'bar'


def test_local_resource_with_relative_path_is_loaded():
    package = Package('data/datapackage_with_foo.txt_resource.json')
    assert len(package.resources) == 1
    assert package.resources[0].source.endswith('foo.txt')


@httpretty.activate
def test_remote_resource_is_loaded():
    url = 'http://someplace.com/resource.txt'
    httpretty.register_uri(httpretty.GET, url, body='foo')
    descriptor = {
        'resources': [
            {'url': url},
        ],
    }
    package = Package(descriptor)
    assert len(package.resources) == 1
    assert package.resources[0].source == 'http://someplace.com/resource.txt'


def test_changing_resources_in_descriptor_changes_datapackage():
    descriptor = {
        'resources': [
            {'data': '万事开头难'}
        ]
    }
    package = Package(descriptor)
    package.descriptor['resources'][0]['name'] = 'saying'
    package.commit()
    assert package.descriptor['resources'][0]['name'] == 'saying'


def test_can_add_resource_to_descriptor_in_place():
    resource = {
        'data': '万事开头难',
    }
    package = Package()
    resources = package.descriptor.get('resources', [])
    resources.append(resource)
    package.descriptor['resources'] = resources
    package.commit()
    assert len(package.resources) == 1
    assert package.resources[0].source == '万事开头难'


def test_can_remove_resource_from_descriptor_in_place():
    descriptor = {
        'resources': [
            {'data': '万事开头难'},
            {'data': 'All beginnings are hard'}
        ]
    }
    package = Package(descriptor)
    del package.descriptor['resources'][1]
    package.commit()
    assert len(package.resources) == 1
    assert package.resources[0].source == '万事开头难'


def test_resources_have_public_backreference_to_package():
    package = Package('data/datapackage/datapackage.json')
    assert package.get_resource('data').package == package


# Save to json

def test_save_as_json(json_tmpfile):
    package = Package({})
    package.save(json_tmpfile.name)
    assert json.loads(json_tmpfile.read().decode('utf-8')) == {
        'profile': 'data-package',
    }


# TODO: use a self-removing directory
def test_save_as_json_base_path(json_tmpfile):
    package = Package({}, base_path='/tmp')
    package.save(json_tmpfile.name, to_base_path=True)
    with open(os.path.join('/tmp', json_tmpfile.name), 'r') as test_file:
        assert json.loads(test_file.read()) == {
        'profile': 'data-package',
    }


# Save to zip

@pytest.mark.skip('deprecated')
def test_saves_as_zip(tmpfile):
    package = Package(schema={})
    package.save(tmpfile)
    assert zipfile.is_zipfile(tmpfile)


def test_accepts_file_paths(tmpfile):
    package = Package(schema={})
    package.save(tmpfile.name)
    assert zipfile.is_zipfile(tmpfile.name)


def test_adds_datapackage_descriptor_at_zipfile_root(tmpfile):
    descriptor = {
        'name': 'proverbs',
        'resources': [
            {'data': '万事开头难'}
        ]
    }
    schema = {}
    package = Package(descriptor, schema)
    package.save(tmpfile)
    with zipfile.ZipFile(tmpfile, 'r') as z:
        package_json = z.read('datapackage.json').decode('utf-8')
    assert json.loads(package_json) == json.loads(package.to_json())


def test_generates_filenames_for_named_resources(tmpfile):
    descriptor = {
        'name': 'proverbs',
        'resources': [
            {'name': 'proverbs', 'format': 'TXT', 'path': 'unicode.txt'},
            {'name': 'proverbs_without_format', 'path': 'unicode.txt'}
        ]
    }
    schema = {}
    package = Package(descriptor, schema, default_base_path='data')
    package.save(tmpfile)
    with zipfile.ZipFile(tmpfile, 'r') as z:
        assert 'data/proverbs.txt' in z.namelist()
        assert 'data/proverbs_without_format' in z.namelist()


def test_generates_unique_filenames_for_unnamed_resources(tmpfile):
    descriptor = {
        'name': 'proverbs',
        'resources': [
            {'path': 'unicode.txt'},
            {'path': 'foo.txt'}
        ]
    }
    schema = {}
    package = Package(descriptor, schema, default_base_path='data')
    package.save(tmpfile)
    with zipfile.ZipFile(tmpfile, 'r') as z:
        files = z.namelist()
        assert sorted(set(files)) == sorted(files)


def test_adds_resources_inside_data_subfolder(tmpfile):
    descriptor = {
        'name': 'proverbs',
        'resources': [
            {'name': 'name', 'path': 'unicode.txt'}
        ]
    }
    schema = {}
    package = Package(descriptor, schema, default_base_path='data')
    package.save(tmpfile)
    with zipfile.ZipFile(tmpfile, 'r') as z:
        filename = [name for name in z.namelist()
                    if name.startswith('data/')]
        assert len(filename) == 1
        resource_data = z.read(filename[0]).decode('utf-8')
    assert resource_data == '万事开头难\n'


def test_fixes_resources_paths_to_be_relative_to_package(tmpfile):
    descriptor = {
        'name': 'proverbs',
        'resources': [
            {'name': 'unicode', 'format': 'txt', 'path': 'unicode.txt'}
        ]
    }
    schema = {}
    pakage = Package(
        descriptor, schema, default_base_path='data')
    pakage.save(tmpfile)
    with zipfile.ZipFile(tmpfile, 'r') as z:
        json_string = z.read('datapackage.json').decode('utf-8')
        generated_pakage_dict = json.loads(json_string)
    assert generated_pakage_dict['resources'][0]['path'] == 'data/unicode.txt'


@pytest.mark.skip(reason='Wait for specs-v1.rc2 resource.data/path')
def test_works_with_resources_with_relative_paths(tmpfile):
    package = Package('data/datapackage_with_foo.txt_resource.json')
    package.save(tmpfile)
    with zipfile.ZipFile(tmpfile, 'r') as z:
        assert len(z.filelist) == 2


@pytest.mark.skip
def test_should_raise_validation_error_if_datapackage_is_invalid(tmpfile):
    descriptor = {}
    schema = {
        'properties': {
            'name': {},
        },
        'required': ['name'],
    }
    package = Package(descriptor, schema)
    with pytest.raises(exceptions.ValidationError):
        package.save(tmpfile)


def test_should_raise_if_path_doesnt_exist():
    package = Package({}, {})
    with pytest.raises(exceptions.DataPackageException):
        package.save('/non/existent/file/path')


@mock.patch('zipfile.ZipFile')
def test_should_raise_if_zipfile_raised_BadZipfile(zipfile_mock, tmpfile):
    zipfile_mock.side_effect = zipfile.BadZipfile()
    package = Package({}, {})
    with pytest.raises(exceptions.DataPackageException):
        package.save(tmpfile)


@mock.patch('zipfile.ZipFile')
def test_should_raise_if_zipfile_raised_LargeZipFile(zipfile_mock, tmpfile):
    zipfile_mock.side_effect = zipfile.LargeZipFile()
    package = Package({}, {})
    with pytest.raises(exceptions.DataPackageException):
        package.save(tmpfile)


# Load from zip

@pytest.mark.skip(reason='Wait for specs-v1.rc2 resource.data/path')
def test_it_works_with_local_paths(datapackage_zip):
    package = Package(datapackage_zip.name)
    assert package.descriptor['name'] == 'proverbs'
    assert len(package.resources) == 1
    assert package.resources[0].data == b'foo\n'


@pytest.mark.skip(reason='Wait for specs-v1.rc2 resource.data/path')
def test_it_works_with_file_objects(datapackage_zip):
    package = Package(datapackage_zip)
    assert package.descriptor['name'] == 'proverbs'
    assert len(package.resources) == 1
    assert package.resources[0].data == b'foo\n'


@pytest.mark.skip(reason='Wait for specs-v1.rc2 resource.data/path')
def test_it_works_with_remote_files(datapackage_zip):
    httpretty.enable()
    datapackage_zip.seek(0)
    url = 'http://someplace.com/datapackage.zip'
    httpretty.register_uri(
        httpretty.GET, url, body=datapackage_zip.read(), content_type='application/zip')
    package = Package(url)
    assert package.descriptor['name'] == 'proverbs'
    assert len(package.resources) == 1
    assert package.resources[0].data == b'foo\n'
    httpretty.disable()


@pytest.mark.skip(reason='Wait for specs-v1.rc2 resource.data/path')
def test_it_removes_temporary_directories(datapackage_zip):
    tempdirs_glob = os.path.join(tempfile.gettempdir(), '*-datapackage')
    original_tempdirs = glob.glob(tempdirs_glob)
    package = Package(datapackage_zip)
    package.save(datapackage_zip)
    del package
    assert glob.glob(tempdirs_glob) == original_tempdirs


@pytest.mark.skip(reason='Wait for specs-v1.rc2 resource.data/path')
def test_local_data_path(datapackage_zip):
    package = Package(datapackage_zip)
    assert package.resources[0].local_data_path is not None
    with open('data/foo.txt') as data_file:
        with open(package.resources[0].local_data_path) as local_data_file:
            assert local_data_file.read() == data_file.read()


def test_it_can_load_from_zip_files_inner_folders(tmpfile):
    descriptor = {
        'profile': 'data-package',
    }
    with zipfile.ZipFile(tmpfile.name, 'w') as z:
        z.writestr('foo/datapackage.json', json.dumps(descriptor))
    package = Package(tmpfile.name, {})
    assert package.descriptor == descriptor


def test_it_breaks_if_theres_no_datapackage_json(tmpfile):
    with zipfile.ZipFile(tmpfile.name, 'w') as z:
        z.writestr('data.txt', 'foobar')
    with pytest.raises(exceptions.DataPackageException):
        Package(tmpfile.name, {})


def test_it_breaks_if_theres_more_than_one_datapackage_json(tmpfile):
    descriptor_foo = {
        'name': 'foo',
    }
    descriptor_bar = {
        'name': 'bar',
    }
    with zipfile.ZipFile(tmpfile.name, 'w') as z:
        z.writestr('foo/datapackage.json', json.dumps(descriptor_foo))
        z.writestr('bar/datapackage.json', json.dumps(descriptor_bar))
    with pytest.raises(exceptions.DataPackageException):
        Package(tmpfile.name, {})


# Deprecated

def test_init_uses_base_schema_by_default():
    package = Package()
    assert package.schema.title == 'Data Package'


@mock.patch('datapackage.registry.Registry')
def test_schema_gets_from_registry_if_available(registry_class_mock):
    schema = {'foo': 'bar'}
    registry_mock = mock.MagicMock()
    registry_mock.get.return_value = schema
    registry_class_mock.return_value = registry_mock
    assert Package().schema.to_dict() == schema


def test_to_dict_value_can_be_altered_without_changing_the_package():
    descriptor = {
        'profile': 'data-package',
    }
    package = Package(descriptor)
    package_dict = package.to_dict()
    package_dict['foo'] = 'bar'
    assert package.descriptor == {
        'profile': 'data-package',
    }


def test_without_resources_is_safe():
    descriptor = {}
    package = Package(descriptor, {})
    assert package.safe()


def test_with_local_resources_with_inexistent_path_isnt_safe():
    descriptor = {
        'resources': [
            {'path': '/foo/bar'},
        ]
    }
    with pytest.raises(exceptions.DataPackageException):
        Package(descriptor, {})


def test_with_local_resources_with_existent_path_isnt_safe():
    descriptor = {
        'resources': [
            {'path': 'data/foo.txt'},
        ]
    }
    with pytest.raises(exceptions.DataPackageException):
        Package(descriptor, {})


def test_descriptor_dict_without_local_resources_is_safe():
    descriptor = {
        'resources': [
            {'data': 42},
            {'url': 'http://someplace.com/data.csv'},
        ]
    }
    package = Package(descriptor, {})
    assert package.safe()


@pytest.mark.skip('deprecated')
def test_local_with_relative_resources_paths_is_safe():
    package = Package('data/datapackage_with_foo.txt_resource.json', {})
    assert package.safe()


def test_local_with_resources_outside_base_path_isnt_safe(tmpfile):
    descriptor = {
        'resources': [
            {'path': __file__},
        ]
    }
    tmpfile.write(json.dumps(descriptor).encode('utf-8'))
    tmpfile.flush()
    with pytest.raises(exceptions.DataPackageException):
        Package(tmpfile.name, {})


def test_local_relative_parent_path_with_unsafe_option_issue_171():
    descriptor = {'resources': [{'name': 'table', 'path': 'data/../data/table.csv'}]}
    # unsafe=false (default)
    with pytest.raises(exceptions.DataPackageException) as excinfo:
        package = Package(descriptor)
    assert 'is not safe' in str(excinfo.value)
    # unsafe=true
    package = Package(descriptor, unsafe=True)
    assert package.get_resource('table').read() == [['1', 'english'], ['2', '中国人']]


@pytest.mark.skip(reason='Wait for specs-v1.rc2 resource.data/path')
def test_zip_with_relative_resources_paths_is_safe(datapackage_zip):
    package = Package(datapackage_zip.name, {})
    assert package.safe()


def test_zip_with_resources_outside_base_path_isnt_safe(tmpfile):
    descriptor = {
        'resources': [
            {'path': __file__},
        ]
    }
    with zipfile.ZipFile(tmpfile.name, 'w') as z:
        z.writestr('datapackage.json', json.dumps(descriptor))
    with pytest.raises(exceptions.DataPackageException):
        Package(tmpfile.name, {})


@pytest.mark.skip('deprecated')
def test_base_path_defaults_to_none():
    assert Package().base_path is None


@pytest.mark.skip('deprecated')
def test_schema():
    descriptor = {}
    schema = {'foo': 'bar'}
    package = Package(descriptor, schema=schema)
    assert package.schema.to_dict() == schema


@pytest.mark.skip('deprecated')
@mock.patch('datapackage.registry.Registry')
def test_schema_raises_registryerror_if_registry_raised(registry_mock):
    registry_mock.side_effect = exceptions.RegistryError
    with pytest.raises(exceptions.RegistryError):
        Package()


@pytest.mark.skip('deprecated')
def test_attributes():
    descriptor = {
        'name': 'test',
        'title': 'a test',
        'profile': 'data-package',
    }
    schema = {
        'properties': {
            'name': {}
        }
    }
    package = Package(descriptor, schema)
    assert sorted(package.attributes) == sorted(['name', 'title', 'profile'])


@pytest.mark.skip('deprecated')
def test_attributes_can_be_set():
    descriptor = {
        'profile': 'data-package',
    }
    package = Package(descriptor)
    package.descriptor['title'] = 'bar'
    assert package.to_dict() == {'profile': 'data-package', 'title': 'bar'}


@pytest.mark.skip('deprecated')
def test_attributes_arent_immutable():
    descriptor = {
        'profile': 'data-package',
        'keywords': [],
    }
    package = Package(descriptor)
    package.descriptor['keywords'].append('foo')
    assert package.to_dict() == {'profile': 'data-package', 'keywords': ['foo']}


@pytest.mark.skip('deprecated')
def test_attributes_return_defaults_id_descriptor_is_empty():
    descriptor = {}
    schema = {}
    package = Package(descriptor, schema)
    assert package.attributes == ('profile',)


@pytest.mark.skip('deprecated')
def test_validate():
    descriptor = {
        'name': 'foo',
    }
    schema = {
        'properties': {
            'name': {},
        },
        'required': ['name'],
    }
    pakcage = Package(descriptor, schema)
    pakcage.validate()


@pytest.mark.skip('deprecated')
def test_validate_works_when_setting_attributes_after_creation():
    schema = {
        'properties': {
            'name': {}
        },
        'required': ['name'],
    }
    package = Package(schema=schema)
    package.descriptor['name'] = 'foo'
    package.validate()


@pytest.mark.skip('deprecated')
def test_validate_raises_validation_error_if_invalid():
    schema = {
        'properties': {
            'name': {},
        },
        'required': ['name'],
    }
    package = Package(schema=schema)
    with pytest.raises(exceptions.ValidationError):
        package.validate()


@pytest.mark.skip('deprecated')
@mock.patch('datapackage.datapackage.Profile')
def test_iter_errors_returns_schemas_iter_errors(profile_mock):
    iter_errors_mock = mock.Mock()
    iter_errors_mock.return_value = 'the iter errors'
    profile_mock.return_value.iter_errors = iter_errors_mock
    descriptor = {'resources': [{'name': 'name', 'data': ['data']}]}
    package = Package(descriptor)
    assert package.iter_errors() == 'the iter errors'
    iter_errors_mock.assert_called_with(package.to_dict())


@pytest.mark.skip('deprecated')
def test_required_attributes():
    schema = {
        'required': ['name', 'title'],
    }
    package = Package(schema=schema)
    assert package.required_attributes == ('name', 'title')


@pytest.mark.skip('deprecated')
def test_required_attributes_return_empty_tuple_if_nothings_required():
    schema = {}
    package = Package(schema=schema)
    assert package.required_attributes == ()


# Foreign keys

FK_DESCRIPTOR = {
  'resources': [
    {
      'name': 'main',
      'data': [
        ['id', 'name', 'surname', 'parent_id'],
        ['1', 'Alex', 'Martin', ''],
        ['2', 'John', 'Dockins', '1'],
        ['3', 'Walter', 'White', '2'],
      ],
      'schema': {
        'fields': [
          {'name': 'id'},
          {'name': 'name'},
          {'name': 'surname'},
          {'name': 'parent_id'},
        ],
        'foreignKeys': [
          {
            'fields': 'name',
            'reference': {'resource': 'people', 'fields': 'firstname'},
          },
        ],
      },
    }, {
      'name': 'people',
      'data': [
        ['firstname', 'surname'],
        ['Alex', 'Martin'],
        ['John', 'Dockins'],
        ['Walter', 'White'],
      ],
    },
  ],
}


def test_single_field_foreign_key():
    resource = Package(FK_DESCRIPTOR).get_resource('main')
    rows = resource.read(relations=True)
    assert rows == [
      ['1', {'firstname': 'Alex', 'surname': 'Martin'}, 'Martin', None],
      ['2', {'firstname': 'John', 'surname': 'Dockins'}, 'Dockins', '1'],
      ['3', {'firstname': 'Walter', 'surname': 'White'}, 'White', '2'],
    ]


def test_single_field_foreign_key_invalid():
    descriptor = deepcopy(FK_DESCRIPTOR)
    descriptor['resources'][1]['data'][2][0] = 'Max'
    resource = Package(descriptor).get_resource('main')
    with pytest.raises(exceptions.RelationError) as excinfo1:
        resource.read(relations=True)
    with pytest.raises(exceptions.RelationError) as excinfo2:
        resource.check_relations()
    assert 'Foreign key' in str(excinfo1.value)
    assert 'Foreign key' in str(excinfo2.value)


def test_single_self_field_foreign_key():
    descriptor = deepcopy(FK_DESCRIPTOR)
    descriptor['resources'][0]['schema']['foreignKeys'][0]['fields'] = 'parent_id'
    descriptor['resources'][0]['schema']['foreignKeys'][0]['reference']['resource'] = ''
    descriptor['resources'][0]['schema']['foreignKeys'][0]['reference']['fields'] = 'id'
    resource = Package(descriptor).get_resource('main')
    keyed_rows = resource.read(keyed=True, relations=True)
    assert keyed_rows == [
      {
          'id': '1',
          'name': 'Alex',
          'surname': 'Martin',
          'parent_id': None,
      },
      {
          'id': '2',
          'name': 'John',
          'surname': 'Dockins',
          'parent_id': {'id': '1', 'name': 'Alex', 'surname': 'Martin', 'parent_id': None},
      },
      {
          'id': '3',
          'name': 'Walter',
          'surname': 'White',
          'parent_id': {'id': '2', 'name': 'John', 'surname': 'Dockins', 'parent_id': '1'},
      },
    ]


def test_single_self_field_foreign_key_invalid():
    descriptor = deepcopy(FK_DESCRIPTOR)
    descriptor['resources'][0]['schema']['foreignKeys'][0]['fields'] = 'parent_id'
    descriptor['resources'][0]['schema']['foreignKeys'][0]['reference']['resource'] = ''
    descriptor['resources'][0]['schema']['foreignKeys'][0]['reference']['fields'] = 'id'
    descriptor['resources'][0]['data'][2][0] = '0'
    resource = Package(descriptor).get_resource('main')
    with pytest.raises(exceptions.RelationError) as excinfo1:
        resource.read(relations=True)
    with pytest.raises(exceptions.RelationError) as excinfo2:
        resource.check_relations()
    assert 'Foreign key' in str(excinfo1.value)
    assert 'Foreign key' in str(excinfo2.value)


def test_multi_field_foreign_key():
    descriptor = deepcopy(FK_DESCRIPTOR)
    descriptor['resources'][0]['schema']['foreignKeys'][0]['fields'] = ['name', 'surname']
    descriptor['resources'][0]['schema']['foreignKeys'][0]['reference']['fields'] = ['firstname', 'surname']
    resource = Package(descriptor).get_resource('main')
    keyed_rows = resource.read(keyed=True, relations=True)
    assert keyed_rows == [
      {
          'id': '1',
          'name': {'firstname': 'Alex', 'surname': 'Martin'},
          'surname': {'firstname': 'Alex', 'surname': 'Martin'},
          'parent_id': None,
      },
      {
          'id': '2',
          'name': {'firstname': 'John', 'surname': 'Dockins'},
          'surname': {'firstname': 'John', 'surname': 'Dockins'},
          'parent_id': '1',
      },
      {
          'id': '3',
          'name': {'firstname': 'Walter', 'surname': 'White'},
          'surname': {'firstname': 'Walter', 'surname': 'White'},
          'parent_id': '2',
      },
    ]


def test_multi_field_foreign_key_invalid():
    descriptor = deepcopy(FK_DESCRIPTOR)
    descriptor['resources'][0]['schema']['foreignKeys'][0]['fields'] = ['name', 'surname']
    descriptor['resources'][0]['schema']['foreignKeys'][0]['reference']['fields'] = ['firstname', 'surname']
    descriptor['resources'][1]['data'][2][0] = 'Max'
    resource = Package(descriptor).get_resource('main')
    with pytest.raises(exceptions.RelationError) as excinfo1:
        resource.read(relations=True)
    with pytest.raises(exceptions.RelationError) as excinfo2:
        resource.check_relations()
    assert 'Foreign key' in str(excinfo1.value)
    assert 'Foreign key' in str(excinfo2.value)


# Storage

def test_load_data_from_storage():
    schema = {
        'fields': [{'format': 'default', 'name': 'id', 'type': 'integer'}],
        'missingValues': ['']
    }
    storage = Mock(
        buckets=['data'],
        describe=lambda bucket: {'fields': [{'name': 'id', 'type': 'integer'}]},
        iter=lambda bucket: [[1], [2], [3]],
        spec=Storage)
    package = Package(storage=storage)
    package.infer()
    resource = package.get_resource('data')
    assert len(package.resources) == 1
    assert resource.descriptor == {
        'name': 'data',
        'path': 'data',
        'profile': 'tabular-data-resource',
        'schema': schema}
    assert resource.headers == ['id']
    assert resource.read() == [[1], [2], [3]]


def test_save_data_to_storage():
    schema = {
        'fields': [{'format': 'default', 'name': 'id', 'type': 'integer'}],
        'missingValues': ['']
    }
    storage = Mock(buckets=['data'], spec=Storage)
    package = Package({'resources': [{'name': 'data', 'data': [['id'], [1], [2], [3]]}]})
    package.save(storage=storage)
    storage.create.assert_called_with(['data'], [schema], force=True)
    storage.write.assert_called_with('data', ANY)


# Compression

@pytest.mark.skipif(six.PY2, reason='Support only for Python3')
def test_package_compression_implicit_gz():
    package = Package('data/datapackage-compression/datapackage.json')
    assert package.get_resource('implicit-gz').read(keyed=True) == [
        {'id': 1, 'name': 'english'},
        {'id': 2, 'name': '中国人'},
    ]


@pytest.mark.skipif(six.PY2, reason='Support only for Python3')
def test_package_compression_implicit_zip():
    package = Package('data/datapackage-compression/datapackage.json')
    assert package.get_resource('implicit-zip').read(keyed=True) == [
        {'id': 1, 'name': 'english'},
        {'id': 2, 'name': '中国人'},
    ]


@pytest.mark.skipif(six.PY2, reason='Support only for Python3')
def test_package_compression_explicit_gz():
    package = Package('data/datapackage-compression/datapackage.json')
    assert package.get_resource('explicit-gz').read(keyed=True) == [
        {'id': 1, 'name': 'english'},
        {'id': 2, 'name': '中国人'},
    ]


@pytest.mark.skipif(six.PY2, reason='Support only for Python3')
def test_package_compression_explicit_zip():
    package = Package('data/datapackage-compression/datapackage.json')
    assert package.get_resource('explicit-zip').read(keyed=True) == [
        {'id': 1, 'name': 'english'},
        {'id': 2, 'name': '中国人'},
    ]


# Groups

@pytest.mark.skipif(six.PY2, reason='Support only for Python3')
def test_package_groups():
    package = Package('data/datapackage-groups/datapackage.json')

    # Check individual resources
    for year in [2016, 2017, 2018]:
        assert package.get_resource('cars-%s' % year).read(keyed=True) == [
            {'name': 'bmw', 'value': year},
            {'name': 'tesla', 'value': year},
            {'name': 'nissan', 'value': year},
        ]

    # Check resources as a group
    group = package.get_group('cars')
    assert group.name == 'cars'
    assert group.headers == ['name', 'value']
    assert group.schema.field_names == ['name', 'value']
    assert group.read(keyed=True) == [
        {'name': 'bmw', 'value': 2016},
        {'name': 'tesla', 'value': 2016},
        {'name': 'nissan', 'value': 2016},
        {'name': 'bmw', 'value': 2017},
        {'name': 'tesla', 'value': 2017},
        {'name': 'nissan', 'value': 2017},
        {'name': 'bmw', 'value': 2018},
        {'name': 'tesla', 'value': 2018},
        {'name': 'nissan', 'value': 2018},
    ]


@pytest.mark.skipif(six.PY2, reason='Support only for Python3')
def test_package_groups_save_to_sql():
    package = Package('data/datapackage-groups/datapackage.json')

    # Save to storage
    engine = sqlalchemy.create_engine('sqlite://')
    storage = Storage.connect('sql', engine=engine)
    package.save(storage=storage)

    # Check storage
    storage = Storage.connect('sql', engine=engine)
    assert storage.buckets == ['cars_2016', 'cars_2017', 'cars_2018']
    for year in [2016, 2017, 2018]:
        assert storage.describe('cars_%s' % year) == {
            'fields': [
                {'name': 'name', 'type': 'string'},
                {'name': 'value', 'type': 'integer'},
            ],
        }
        assert storage.read('cars_%s' % year) == [
            ['bmw', year],
            ['tesla', year],
            ['nissan', year],
        ]


@pytest.mark.skipif(six.PY2, reason='Support only for Python3')
def test_package_groups_save_to_sql_merge_groups():
    package = Package('data/datapackage-groups/datapackage.json')

    # Save to storage
    engine = sqlalchemy.create_engine('sqlite://')
    storage = Storage.connect('sql', engine=engine)
    package.save(storage=storage, merge_groups=True)

    # Check storage
    storage = Storage.connect('sql', engine=engine)
    assert storage.buckets == ['cars']
    assert storage.describe('cars') == {
        'fields': [
            {'name': 'name', 'type': 'string'},
            {'name': 'value', 'type': 'integer'},
        ],
    }
    assert storage.read('cars') == [
        ['bmw', 2016],
        ['tesla', 2016],
        ['nissan', 2016],
        ['bmw', 2017],
        ['tesla', 2017],
        ['nissan', 2017],
        ['bmw', 2018],
        ['tesla', 2018],
        ['nissan', 2018],
    ]

@pytest.mark.skipif(six.PY2, reason='Support only for Python3')
def test_package_groups_check_relations():
    with open('data/datapackage-groups/datapackage.json', 'r', encoding='utf8') as d:
        descriptor = json.load(d)
        # add ForeignKey to schema
        carSchema = {
            "fields": [
                {
                    "name": "name",
                    "type": "string"
                },
                {
                    "name": "value",
                    "type": "integer"
                }
            ],
            "foreignKeys": [{"fields": "name",
                            "reference": {"resource": "brand_country", "fields": "name"}}]
        }
        for r in descriptor["resources"]:
            r['schema'] = carSchema
        # add reference table
        descriptor['resources'].append({
            "name": "brand_country",
            "data": [{"name": "nissan", "country": "Japan"},
                {"name": "bmw", "country": "Germany"},
                {"name": "tesla", "country": "USA"}
            ],
            "profile": "tabular-data-resource",
            "schema": {
                "fields": [
                    {
                        "name": "country",
                        "type": "string"
                    },
                    {
                        "name": "name",
                        "type": "string"
                    }
                ]
            }
        })
        package = Package(descriptor, base_path='data/datapackage-groups/')
        group = package.get_group('cars')

        assert group.check_relations() is True

        descriptor['resources'][-1]['data'] = [{"name": "nissan", "country": "Japan"},
                {"name": "bmw", "country": "Germany"}
            ]
        package = Package(descriptor, base_path='data/datapackage-groups/')
        with pytest.raises(tableschema.exceptions.RelationError) as _:
            package.get_group('cars').check_relations()

# Issues


def test_package_dialect_no_header_issue_167():
    package = Package('data/package_dialect_no_header.json')
    keyed_rows = package.get_resource('people').read(keyed=True)
    assert keyed_rows[0]['score'] == 1
    assert keyed_rows[1]['score'] == 1


def test_package_save_slugify_fk_resource_name_issue_181():
    descriptor = {
        'resources': [
            {
                'name': 'my-langs',
                'data': [['en'], ['ch']],
                'schema': {
                    'fields': [
                        {'name': 'lang'},
                    ]
                }
            },
            {
                'name': 'my-notes',
                'data': [['1', 'en', 'note1'], [2, 'ch', 'note2']],
                'schema': {
                    'fields': [
                        {'name': 'id', 'type': 'integer'},
                        {'name': 'lang'},
                        {'name': 'note'},
                    ],
                    'foreignKeys': [
                        {'fields': 'lang', 'reference': {'resource': 'my-langs', 'fields': 'lang'}}
                    ]
                }
            }
        ]
    }
    storage = Mock(buckets=['my_langs', 'my_notes'], spec=Storage)
    package = Package(descriptor)
    package.save(storage=storage)
    assert storage.create.call_args[0][0] == ['my_langs', 'my_notes']
    assert storage.create.call_args[0][1][1]['foreignKeys'] == [
        {'fields': 'lang', 'reference': {'resource': 'my_langs', 'fields': 'lang'}}
    ]


def test_package_legacy_schema_tabular_issue_197():
    package = Package(None, schema='tabular')


# Fixtures

@pytest.fixture
def datapackage_zip(tmpfile):
    descriptor = {
        'name': 'proverbs',
        'resources': [
            {'name': 'name', 'path': 'foo.txt'},
        ]
    }
    package = Package(descriptor, default_base_path='data')
    package.save(tmpfile)
    return tmpfile
