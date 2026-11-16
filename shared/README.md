# Shared file drop

The Excel / CSV connection wizard can read files from this directory when
`FILE_SOURCE_ROOTS` is unset. The picker only lists supported tabular files
(`.csv`, `.tsv`, `.txt`, `.pcl`, `.xlsx`, `.xls`, `.xlsm`, `.parquet`, `.pq`)
and subdirectories.

Set `FILE_SOURCE_ROOTS` to one or more mounted directories to replace this
default. Paths outside those roots are rejected.
