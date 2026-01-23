"""
Keywords Model - Extract and format sample keywords.

This module provides:
- Extraction of custom keywords from samples
- Tidy format generation (one row per keyword per sample)
- Wide format generation (one row per sample, keywords as columns)
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import pandas as pd

from .workspace_model import Sample


class KeywordsModel:
    """
    Model for extracting and formatting sample keywords.

    Supports two output formats:
    - Tidy: One row per keyword per sample (for pivot_wider in R)
    - Wide: One row per sample, keywords as columns (pivoted by Mouse/Organ)
    """

    def __init__(self):
        self._samples: List[Sample] = []
        self._custom_keyword_names: List[str] = []

    def set_samples(self, samples: List[Sample]) -> None:
        """
        Set the samples to extract keywords from.

        Args:
            samples: List of Sample objects
        """
        self._samples = samples
        self._extract_keyword_names()

    def _extract_keyword_names(self) -> None:
        """Extract unique custom keyword names across all samples."""
        keyword_set = set()
        for sample in self._samples:
            custom = sample.get_custom_keywords()
            keyword_set.update(custom.keys())

        self._custom_keyword_names = sorted(list(keyword_set))

    @property
    def keyword_names(self) -> List[str]:
        """Returns list of unique custom keyword names."""
        return self._custom_keyword_names

    def get_tidy_dataframe(
        self,
        selected_keywords: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Generate tidy format DataFrame.

        Args:
            selected_keywords: If provided, only include these keywords.
                              If None, include all custom keywords.

        Returns DataFrame with columns:
            - sample_id
            - sample_name
            - keyword_name
            - keyword_value

        One row per keyword per sample.
        """
        rows = []

        for sample in self._samples:
            custom = sample.get_custom_keywords()
            # Sort keyword names for consistent ordering across samples
            for kw_name in sorted(custom.keys()):
                # Filter by selected keywords if specified
                if selected_keywords is not None and kw_name not in selected_keywords:
                    continue
                rows.append({
                    'sample_id': sample.sample_id,
                    'sample_name': sample.name,
                    'keyword_name': kw_name,
                    'keyword_value': str(custom[kw_name]) if custom[kw_name] else ''
                })

        return pd.DataFrame(rows)

    def get_available_keywords(self) -> List[str]:
        """
        Return list of all unique custom keywords found across samples.

        This is useful for populating UI selection lists.
        """
        return self._custom_keyword_names.copy()

    def get_wide_dataframe(
        self,
        index_columns: Optional[List[str]] = None,
        selected_keywords: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Generate wide format DataFrame.

        Args:
            index_columns: Keywords to use as row identifiers.
                          If None, uses the first 2 discovered keywords.
                          If empty list [], no special index ordering is applied.
            selected_keywords: If provided, only include these keywords as columns.
                              If None, include all custom keywords.

        Returns DataFrame with:
            - Index columns as specified
            - Other keywords as additional columns
            - sample_id and sample_name
        """
        # Determine which keywords to include
        keywords_to_include = selected_keywords if selected_keywords is not None else self._custom_keyword_names

        if index_columns is None:
            # Auto-discover: use first 2 available keywords as default index
            available = [k for k in self._custom_keyword_names if k in keywords_to_include]
            index_columns = available[:2] if len(available) >= 2 else available.copy()

        rows = []
        for sample in self._samples:
            custom = sample.get_custom_keywords()
            row = {
                'sample_id': sample.sample_id,
                'sample_name': sample.name,
            }
            # Add only selected keywords as columns
            for kw_name in keywords_to_include:
                if kw_name in self._custom_keyword_names:
                    value = custom.get(kw_name, '')
                    row[kw_name] = str(value) if value else ''

            rows.append(row)

        df = pd.DataFrame(rows)

        # Reorder columns: sample_name first (primary identifier), then index_columns,
        # then other keywords, then sample_id at the end for reference
        ordered_cols = ['sample_name']  # Always first as the primary identifier

        # Add user-selected index columns
        for col in index_columns:
            if col in df.columns and col not in ordered_cols:
                ordered_cols.append(col)

        # Add other keyword columns
        for col in keywords_to_include:
            if col not in ordered_cols and col in df.columns:
                ordered_cols.append(col)

        # Add sample_id at the end for reference
        ordered_cols.append('sample_id')

        # Reorder
        final_cols = [c for c in ordered_cols if c in df.columns]
        df = df[final_cols]

        return df

    def get_keywords_for_sample(self, sample_id: str) -> Dict[str, str]:
        """
        Get custom keywords for a specific sample.

        Args:
            sample_id: The sample ID

        Returns:
            Dict of keyword name -> value
        """
        for sample in self._samples:
            if sample.sample_id == sample_id:
                return sample.get_custom_keywords()
        return {}

    def get_keyword_values(self, keyword_name: str) -> List[str]:
        """
        Get all unique values for a specific keyword across samples.

        Args:
            keyword_name: The keyword name

        Returns:
            List of unique values
        """
        values = set()
        for sample in self._samples:
            custom = sample.get_custom_keywords()
            if keyword_name in custom and custom[keyword_name]:
                values.add(str(custom[keyword_name]))

        return sorted(list(values))
