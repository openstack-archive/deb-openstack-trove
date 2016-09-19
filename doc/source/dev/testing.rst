.. _testing:

=========================
Notes on Trove Unit Tests
=========================

Mock Object Library
-------------------

Trove unit tests make a frequent use of the Python Mock library.
This library lets the caller replace (*"mock"*) parts of the system under test with
mock objects and make assertions about how they have been used. [1]_

The Problem of Dangling Mocks
-----------------------------

Often one needs to mock global functions in shared system modules.
The caller must restore the original state of the module
after it is no longer required.

Dangling mock objects in global modules (mocked members of imported
modules that never get restored) have been causing various transient
failures in the unit test suite.

The main issues posed by dangling mock objects include::

    - Such object references propagate across the entire test suite. Any
    caller may be hit by a non-functional - or worse - crippled module member
    because some other (potentially totally unrelated) test case failed to
    restore it.

    - Dangling mock references shared across different test modules may
    lead to unexpected results/behavior in multi-threaded environments. One
    example could be a test case failing because a mock got called multiple
    times from unrelated modules.

Such issues are likely to exhibit transient random behavior depending
on the runtime environment, making them difficult to debug.

There are several possible strategies available for dealing with dangling
mock objects (see the section on recommended patterns).
Further information is available in [1]_, [2]_, [3]_.

Dangling Mock Detector
----------------------

All Trove unit tests should extend 'trove_testtools.TestCase'.
It is a subclass of 'testtools.TestCase' which automatically checks for
dangling mock objects at each test class teardown.
It marks the tests as failed and reports the leaked reference if it
finds any.

Recommended Mocking Patterns
----------------------------

Mocking a class or object shared across multiple test cases.
Use the patcher pattern in conjunction with the setUp()
method [ see section 26.4.3.5. of [1]_ ].

.. code-block:: python

    def setUp(self):
        super(CouchbaseBackupTests, self).setUp()
        self.exe_timeout_patch = patch.object(utils, 'execute_with_timeout')
        self.addCleanup(self.exe_timeout_patch.stop)

    def test_case(self):
        mock_exe_timeout = self.exe_timeout_patch.start()

If the mock object is required in the majority of test cases the following
pattern may be more efficient.

.. code-block:: python

    def setUp(self):
        super(CouchbaseBackupTests, self).setUp()
        self.exe_timeout_patch = patch.object(utils, 'execute_with_timeout')
        self.addCleanup(self.exe_timeout_patch.stop)
        self.mock_exe_timeout = self.exe_timeout_patch.start()

    def test_case(self):
        # All test cases can now reference 'self.mock_exe_timeout'.

- Note also: patch.stopall()
  This method stops all active patches that were started with start.

Mocking a class or object for a single entire test case.
Use the decorator pattern.

.. code-block:: python

    @patch.object(utils, 'execute_with_timeout')
    @patch.object(os, 'popen')
    def test_case(self, popen_mock, execute_with_timeout_mock):
        pass

    @patch.multiple(utils, execute_with_timeout=DEFAULT,
                    generate_random_password=MagicMock(return_value=1))
    def test_case(self, generate_random_password, execute_with_timeout):
        pass

Mocking a class or object for a smaller scope within one test case.
Use the context manager pattern.

.. code-block:: python

    def test_case(self):
        # Some code using real implementation of 'generate_random_password'.
        with patch.object(utils, 'generate_random_password') as pwd_mock:
            # Using the mocked implementation of 'generate_random_password'.
        # Again code using the actual implementation of the method.

    def test_case(self):
        with patch.multiple(utils, execute_with_timeout_mock=DEFAULT,
                            generate_random_password=MagicMock(
                                return_value=1)) as mocks:
            password_mock = mocks['generate_random_password']
            execute_mock = mocks['execute_with_timeout_mock']

Mocking global configuration properties.
Use 'patch_conf_property' method from 'trove_testtools.TestCase'.

.. code-block:: python

    def test_case(self):
        self.patch_conf_property('max_accepted_volume_size', 10)

Datastore-specific configuration properties can be mocked by passing
an optional 'section' argument to the above call.

.. code-block:: python

    def test_case(self):
        self.patch_conf_property('cluster_support', False, section='redis')

- Note also: 'patch_datastore_manager()'
  'datastore_manager' name has to be set properly when testing
  datastore-specific code to ensure correct configuration options get loaded.
  This is a convenience method for mocking 'datastore_manager' name.

.. code-block:: python

    def test_case(self):
        self.patch_datastore_manager('cassandra')

References
----------

.. [1] Mock Guide: https://docs.python.org/3/library/unittest.mock.html
.. [2] Python Mock Gotchas: http://alexmarandon.com/articles/python_mock_gotchas/
.. [3] Mocking Mistakes: http://engineroom.trackmaven.com/blog/mocking-mistakes/
