# HO112 and Yeo2011 atlas provenance

## Project contract

`SSL/src/dgda/atlas.py` defines HO112 as the concatenation of DPARSF
ROISignals columns 117-212 (96 cortical ROIs) and 213-228 (16
subcortical ROIs). The matching source is the DPABI YCG Harvard-Oxford
template pair, not an arbitrary 112-region Harvard-Oxford derivative.

The downloaded DPABI templates were verified against the GitHub blob
identifiers recorded in `source_manifest.json`:

- `HarvardOxford-cort-maxprob-thr25-2mm_YCG.nii`: 96 non-background labels.
- `HarvardOxford-sub-maxprob-thr25-2mm_YCG.nii`: 16 non-background labels.
- The associated `Reference` arrays define the feature order: all 96
  cortical rows followed by all 16 subcortical rows.

Source: <https://github.com/Chaogan-Yan/DPABI/tree/master/Templates>

## Yeo network atlas

The Yeo2011 nonlinear MNI152 release was downloaded from the FreeSurfer
distribution:

<https://surfer.nmr.mgh.harvard.edu/pub/data/Yeo_JNeurophysiol11_MNI152.zip>

The liberal-mask 7-network volume is used for the derived mapping. The
tight mask failed the pre-registered 0.20 dominant-overlap threshold for
five cortical HO parcels. With the liberal mask, all 96 cortical parcels
pass (minimum dominant overlap 0.260; mean 0.653). The 16 subcortical
ROIs remain explicitly `Subcortical` because Yeo2011 is a cortical atlas.

## Derived files

- `derived/ho112_dpabi_labels.csv`: exact DPABI MAT order and atlas values.
- `derived/yeo2011_7networks_labels.csv`: canonical Yeo7 names.
- `derived/ho112_to_yeo7_liberal.csv`: verified dominant-overlap mapping.
- `derived/ho112_to_yeo7_liberal.manifest.json`: mapping input hashes.

The dominant-network mapping is suitable for coarse network-pair
aggregation. Broad anatomical parcels with low overlap should not be
presented as uniquely belonging to one functional network; retain and
report `overlap_fraction` in interpretation tables.

## Rebuild

```bash
python scripts/45_build_ho112_yeo_mapping.py \
  --ho_cortical_atlas resources/atlases/dpabi_ho112/HarvardOxford-cort-maxprob-thr25-2mm_YCG.nii \
  --ho_subcortical_atlas resources/atlases/dpabi_ho112/HarvardOxford-sub-maxprob-thr25-2mm_YCG.nii \
  --yeo_atlas resources/atlases/yeo2011/Yeo2011_7Networks_MNI152_FreeSurferConformed1mm_LiberalMask.nii.gz \
  --ho_labels resources/atlases/derived/ho112_dpabi_labels.csv \
  --yeo_labels resources/atlases/derived/yeo2011_7networks_labels.csv \
  --output resources/atlases/derived/ho112_to_yeo7_liberal.csv \
  --minimum_overlap 0.20
```
