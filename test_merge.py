import unittest
from merge_rff import sort_key_for_rff_name, merge_records_with_precedence

class TestMergeRFF(unittest.TestCase):
    def test_sort_key_for_rff_name(self):
        # Q1..Q4 sorting
        self.assertEqual(sort_key_for_rff_name("file_2023_Q2.rff"), (2023, 2, "file_2023_Q2.rff"))
        self.assertEqual(sort_key_for_rff_name("file_2023_Q1.rff"), (2023, 1, "file_2023_Q1.rff"))
        self.assertEqual(sort_key_for_rff_name("file_Q4.rff"), (9999, 4, "file_Q4.rff"))
        self.assertEqual(sort_key_for_rff_name("some_name.rff"), (9999, 99, "some_name.rff"))
        
        # Check sorting order
        names = ["2023_Q3.rff", "2023_Q1.rff", "2022_Q4.rff"]
        sorted_names = sorted(names, key=sort_key_for_rff_name)
        self.assertEqual(sorted_names, ["2022_Q4.rff", "2023_Q1.rff", "2023_Q3.rff"])

    def test_merge_records_with_precedence(self):
        # List of record lists: each list is [(float, float), ...] representing (time, value)
        file1 = [(1.0, 0.5), (2.0, 0.0), (3.0, 1.2)]
        file2 = [(2.0, 0.1), (3.0, 1.2), (4.0, 0.8)]
        
        merged = merge_records_with_precedence([file1, file2])
        # File 2 should overwrite File 1 for timestamps 2.0 and 3.0
        expected = [(1.0, 0.5), (2.0, 0.1), (3.0, 1.2), (4.0, 0.8)]
        self.assertEqual(merged, expected)

if __name__ == '__main__':
    unittest.main()
