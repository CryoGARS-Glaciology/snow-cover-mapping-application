"""
Utilities for modeling and analyzing snow cover trends
Rainey Aberle
2023
"""

import math
import pandas as pd
import glob
import geopandas as gpd
import os
from tqdm.auto import tqdm
import numpy as np
import xarray as xr
import rioxarray as rxr
from sklearn.model_selection import KFold
from sklearn.inspection import permutation_importance
from joblib import dump, load
import matplotlib.pyplot as plt
import sklearn


def convert_wgs_to_utm(lon: float, lat: float):
    """
    Return best UTM epsg-code based on WGS84 lat and lon coordinate pair

    Parameters
    ----------
    lon: float
        longitude coordinate
    lat: float
        latitude coordinate

    Returns
    ----------
    epsg_code: str
        optimal UTM zone, e.g. "32606"
    """
    utm_band = str((math.floor((lon + 180) / 6) % 60) + 1)
    if len(utm_band) == 1:
        utm_band = '0' + utm_band
    if lat >= 0:
        epsg_code = '326' + utm_band
        return epsg_code
    epsg_code = '327' + utm_band
    return epsg_code


def determine_subregion_name_color(o1, o2):
    if (o1 == 1.0) and (o2 == 1.0):
        subregion_name, color = 'Brooks Range', 'c'
    elif (o1 == 1.0) and (o2 == 2.0):
        subregion_name, color = 'Alaska Range', '#1f78b4'
    elif (o1 == 1.0) and (o2 == 3.0):
        subregion_name, color = 'Aleutians', '#6d9c43'
    elif (o1 == 1.0) and (o2 == 4.0):
        subregion_name, color = 'W. Chugach Mtns.', '#264708'
    elif (o1 == 1.0) and (o2 == 5.0):
        subregion_name, color = 'St. Elias Mtns.', '#fb9a99'
    elif (o1 == 1.0) and (o2 == 6.0):
        subregion_name, color = 'N. Coast Ranges', '#e31a1c'
    elif (o1 == 2.0) and (o2 == 1.0):
        subregion_name, color = 'N. Rockies', '#cab2d6'
    elif (o1 == 2.0) and (o2 == 2.0):
        subregion_name, color = 'N. Cascades', '#fdbf6f'
    elif (o1 == 2.0) and (o2 == 3.0):
        subregion_name, color = 'C. Rockies', '#9657d9'
    elif (o1 == 2.0) and (o2 == 4.0):
        subregion_name, color = 'S. Cascades', '#ff7f00'
    elif (o1 == 2.0) and (o2 == 5.0):
        subregion_name, color = 'S. Rockies', '#6a3d9a'
    else:
        subregion_name = 'O1:' + o1 + ' O2:' + o2
        color = 'k'

    return subregion_name, color


def calculate_sla_bounds(stats_df, dem, snow_cover_mask, dx, verbose=False):
    """
    Calculate uncertainty in snowline altitude derived from the transient AAR using the distribution of 
    snow-free pixels above the snowline and snow-covered pixels below the snowline.
    
    Parameters
    ----------
    stats_df: pandas.dataframe.DataFrame
        snow cover statistics table
    dem: xarray.Dataset | xarray.DataArray
        digital elevation model clipped to the glacier area
    snow_cover_mask = xarray.Dataset | xarray.DataArray
        mask of snow cover from the classified image
    dx: float 
        ground area of each image pixel
    verbose: bool (=False)
        whether to print statistics
        
    Returns
    ----------
    sla: float
        snowline altitude (1-AAR percentile of the DEM), in units of DEM (usually meters)
    sla_upper_bound: float
        snowline altitude upper bound, in units of DEM (usually meters)
    sla_lower_bounds: float
        snowline altitude lower bound, in units of DEM (usually meters)
    """
    # Get original snow cover stats and SLA percentile from DataFrame
    aar = stats_df['AAR']
    sla = stats_df['ELA_from_AAR_m']
    sla_percentile = 1 - aar

    # Calculate glacier area
    npx = len(np.argwhere(~np.isnan(dem.data.ravel())).ravel())
    total_area = npx * dx**2
        
    # Calculate areas of misclassified pixels
    snow_free_above_sla = xr.where((dem > sla) & (snow_cover_mask == 0), 1, 0)
    snow_free_above_sla_area = len(np.argwhere(snow_free_above_sla.data.ravel()==1).ravel()) * dx**2
    snow_covered_below_sla = xr.where((dem < sla) & (snow_cover_mask == 1), 1, 0)
    snow_covered_below_sla_area = len(np.argwhere(snow_covered_below_sla.data.ravel()==1).ravel()) * dx**2

    # Convert areas to percentiles
    delta_up = snow_free_above_sla_area / total_area
    delta_down = snow_covered_below_sla_area / total_area
        
    # Adjust SLA percentiles
    upper_sla_percentile = sla_percentile + delta_up
    lower_sla_percentile = sla_percentile - delta_down
    # Make sure percentiles are within [0,1]
    upper_sla_percentile, lower_sla_percentile = np.clip([upper_sla_percentile, lower_sla_percentile], 0, 1)

    # Calculate SLA upper and lower bounds
    sla_upper_bound = np.nanpercentile(dem.data.ravel(), upper_sla_percentile * 100)
    sla_lower_bound = np.nanpercentile(dem.data.ravel(), lower_sla_percentile * 100)

    # Print results if requested
    if verbose:
        print(f"Total area = {np.round(total_area / 1e6,2)} km^2")
        print(f"Area of snow-free pixels above SLA = {np.round(snow_free_above_sla_area / 1e6, 2)} km^2")
        print(f"Area of snow-covered pixels below SLA = {np.round(snow_covered_below_sla_area / 1e6, 2)} km^2")
        print(f"AAR = {np.round(aar, 3)}")
        print(f"SLA percentile = {np.round(sla_percentile, 3)}")
        print(f"SLA upper-bound percentile = {np.round(upper_sla_percentile, 3)}")
        print(f"SLA lower-bound percentile = {np.round(lower_sla_percentile, 3)}")
        print(f"SLA = {np.round(sla, 2)} m")
        print(f"SLA upper-bound = {np.round(sla_upper_bound, 2)} m")
        print(f"SLA lower-bound = {np.round(sla_lower_bound, 2)} m")
        
    return sla, sla_upper_bound, sla_lower_bound


def adjust_data_vars(dem_xr):
    """
    Adjust DEM variables, such that the resulting DEM has one band called "elevation"

    Parameters
    ----------
    dem_xr

    Returns
    ----------
    dem_xr
    
    """
    
    if 'band_data' in dem_xr.data_vars:
        dem_xr = dem_xr.rename({'band_data': 'elevation'})
    if 'band' in dem_xr.dims:
        elev_data = dem_xr.elevation.data[0]
        dem_xr = dem_xr.drop_dims('band')
        dem_xr['elevation'] = (('y', 'x'), elev_data)
    return dem_xr


def calculate_hypsometric_index(dem_fn, aoi):
    """
    Calculate Hypsometric Index using an input DEM file name and area of interest shapefile. 
    Based on Jiskoot et al. (2009): https://doi.org/10.3189/172756410790595796

    Parameters
    ----------
    dem_fn

    aoi

    Returns
    ----------
    hi

    hi_category
    """
    
    # load DEM as DataArray
    dem = rxr.open_rasterio(dem_fn)
    # reproject DEM to AOI CRS
    dem = dem.rio.reproject('EPSG:'+str(aoi.crs.to_epsg()))
    # clip DEM to AOI
    try:
        dem_aoi = dem.rio.clip(aoi.geometry, aoi.crs)
    except:
        return 'N/A', 'N/A'
    # convert to dataset
    dem_aoi_ds = dem_aoi.to_dataset(name='elevation')
    # adjust DEM data variables
    dem_aoi_ds = adjust_data_vars(dem_aoi_ds)
    # set no data values to NaN
    dem_aoi_ds = xr.where((dem_aoi_ds > 1e38) | (dem_aoi_ds <= -9999), np.nan, dem_aoi_ds)
    # check that there is data after removing no data values
    if np.isnan(dem_aoi_ds.elevation.data).all():
        return 'N/A', 'N/A'
    # calculate elevation statistics
    h_max = np.nanmax(np.ravel(dem_aoi_ds.elevation.data))
    h_min = np.nanmin(np.ravel(dem_aoi_ds.elevation.data))
    h_med = np.nanmedian(np.ravel(dem_aoi_ds.elevation.data))
    # calculate HI, where HI = (H_max - H_med) / (H_med - H_min). If 0 < HI < 1, HI = -1/HI.
    hi = (h_max - h_med) / (h_med - h_min)
    if (0 < hi) and (hi < 1):
        hi = -1 / hi
    # determine HI category
    if hi <= -1.5:
        hi_category = 'Very top heavy'
    elif (hi > -1.5) and (hi <= -1.2):
        hi_category = 'Top heavy'
    elif (hi > -1.2) and (hi <= 1.2):
        hi_category = 'Equidimensional'
    elif (hi > 1.2) and (hi <= 1.5):
        hi_category = 'Bottom heavy'
    elif hi > 1.5:
        hi_category = 'Very bottom heavy'

    return hi, hi_category


def construct_site_training_data(study_sites_path, site_name, dem):
    """

    Parameters
    ----------
    study_sites_path: str, os.path
        path to study sites
    site_name: str
        name of site folder
    dem: xarray.Dataset
        digital elevation model over site

    Returns
    -------
    training_df: pandas.DataFrame
        table containing training data for site
    """

    # Load snowlines
    snowlines_df = pd.DataFrame()
    snowlines_path = os.path.join(study_sites_path, site_name)
    snowline_fns = glob.glob(os.path.join(snowlines_path, '*snowlines*.csv'))
    if len(snowline_fns) == 0:
        print('No snowlines found, continuing...')
        return None
    snowlines_df = pd.read_csv(snowline_fns[0])
    snowlines_df['datetime'] = pd.to_datetime(snowlines_df['datetime'])
    snowlines_df['Date'] = snowlines_df['datetime'].values.astype('datetime64[D]')
    # don't include observations from PlanetScope
    snowlines_df = snowlines_df.loc[snowlines_df['dataset'] != 'PlanetScope']

    # Load ERA data
    era_fns = glob.glob(os.path.join(study_sites_path, site_name, 'ERA', '*.csv'))
    era_fn = max(era_fns, key=os.path.getctime)
    era = pd.read_csv(era_fn)
    era.reset_index(drop=True, inplace=True)
    era['Date'] = pd.to_datetime(era['Date'])
    era['Date'] = era['Date'].values.astype('datetime64[D]')
    # Calculate mean annual temperature range and max. precipitation
    annual_min_air_temp_mean = np.nanmean(
        era.groupby(era['Date'].dt.year)['Temperature_Celsius_Adjusted'].min().values)
    annual_max_air_temp_mean = np.nanmean(
        era.groupby(era['Date'].dt.year)['Temperature_Celsius_Adjusted'].max().values)
    era['Water_Year'] = era['Date'].apply(
        lambda x: x.year if x.month >= 10 else x.year - 1)  # add a water year column
    era['Cumulative_Precipitation_Meters'] = era.groupby(era['Water_Year'])[
        'Precipitation_Meters'].cumsum()
    annual_max_precip_mean = np.nanmean(
        era.groupby(era['Date'].dt.year)['Cumulative_Precipitation_Meters'].max().values)

    # Merge the snowlines and climate DataFrames
    training_df = pd.merge(snowlines_df, era, on='Date', how='outer')
    training_df['Mean_Annual_Air_Temp_Range'] = annual_max_air_temp_mean - annual_min_air_temp_mean
    training_df['Mean_Annual_Precipitation_Max'] = annual_max_precip_mean

    # Adjust dataframe
    training_df.sort_values(by='Date', inplace=True)
    training_df.dropna(inplace=True)
    training_df.reset_index(drop=True, inplace=True)
    # select columns
    cols = ['site_name', 'Date', 'AAR', 'ELA_from_AAR_m',
            'Cumulative_Positive_Degree_Days', 'Cumulative_Snowfall_mwe',
            'Mean_Annual_Air_Temp_Range', 'Mean_Annual_Precipitation_Max']
    training_df = training_df[cols]

    # Load RGI outline
    aoi_fn = glob.glob(os.path.join(study_sites_path, site_name, 'AOIs', '*RGI*shp'))[0]
    aoi = gpd.read_file(aoi_fn)
    # reproject to optimal utm zone
    aoi_centroid = [aoi.geometry[0].centroid.xy[0][0],
                    aoi.geometry[0].centroid.xy[1][0]]
    epsg_utm = convert_wgs_to_utm(aoi_centroid[0], aoi_centroid[1])
    aoi_utm = aoi.to_crs('EPSG:' + epsg_utm)
    # calculate perimeter to sqrt(area) ratio
    p_a_ratio = aoi_utm.geometry[0].exterior.length / np.sqrt(aoi_utm.geometry[0].area)
    training_df['PA_Ratio'] = p_a_ratio
    # add terrain parameters to training df
    aoi_columns = ['O1Region', 'O2Region', 'Area', 'Zmin', 'Zmax', 'Zmed', 'Slope', 'Aspect']
    for column in aoi_columns:
        training_df[column] = aoi[column].values[0]

    def adjust_data_vars(im_xr):
        if 'band_data' in im_xr.data_vars:
            im_xr = im_xr.rename({'band_data': 'elevation'})
        if 'band' in im_xr.dims:
            elev_data = im_xr.elevation.data[0]
            im_xr = im_xr.drop_dims('band')
            im_xr['elevation'] = (('y', 'x'), elev_data)
        return im_xr

    # Calculate Hypsometric Index (HI)
    # Jiskoot et al. (2009): https://doi.org/10.3189/172756410790595796
    # clip DEM to AOI
    dem_utm = dem.rio.reproject('EPSG:'+str(aoi.crs.to_epsg()))
    dem_utm_aoi = dem_utm.rio.clip(aoi.geometry, aoi.crs)
    # adjust DEM data variables
    dem_utm_aoi = adjust_data_vars(dem_utm_aoi)
    # set no data values to NaN
    dem_utm_aoi = xr.where((dem_utm_aoi > 1e38) | (dem_utm_aoi <= -9999), np.nan, dem_utm_aoi)
    # calculate elevation statistics
    h_max = np.nanmax(np.ravel(dem_utm_aoi.elevation.data))
    h_min = np.nanmin(np.ravel(dem_utm_aoi.elevation.data))
    h_med = np.nanmedian(np.ravel(dem_utm_aoi.elevation.data))
    # calculate HI, where HI = (H_max - H_med) / (H_med - H_min). If 0 < HI < 1, HI = -1/HI.
    hi = (h_max - h_med) / (h_med - h_min)
    if (0 < hi) and (hi < 1):
        hi = -1 / hi
    # determine HI category
    if hi <= -1.5:
        hi_category = 'Very top heavy'
    elif (hi > -1.5) and (hi <= -1.2):
        hi_category = 'Top heavy'
    elif (hi > -1.2) and (hi <= 1.2):
        hi_category = 'Equidimensional'
    elif (hi > 1.2) and (hi <= 1.5):
        hi_category = 'Bottom heavy'
    elif hi > 1.5:
        hi_category = 'Very bottom heavy'
    training_df['Hypsometric_Index'] = hi
    training_df['Hypsometric_Index_Category'] = hi_category

    return training_df


def determine_best_model(data, models, model_names, feature_columns, labels, out_path,
                         best_model_fn='best_model.joblib', save_performances=False,
                         performances_fn='model_performances.csv', num_folds=10):
    """
    Determine the most accurate machine learning model for your input data using K-folds cross-validation.

    Parameters
    ----------
    data: pandas.DataFrame
        contains data for all feature columns and labels
    models: list of sklearn models
        list of all models to test
    model_names: list of str
        names of each model used for displaying and saving
    feature_columns: list of str
        which columns in data to use for model prediction, i.e. the input variable(s)
    labels: list of str
        which column(s) in data for model prediction, i.e. the target variable(s)
    out_path: str
        path in directory where outputs will be saved
    best_model_fn: str
        best model file name to be saved in out_path
    save_performances: bool
        whether to save data table of performance metrics for each model
    performances_fn: str
        file name for output performances CSV (saved automatically to out_path)
    num_folds: int
        number of folds (K) to use in K-folds cross-validation.

    Returns
    -------
    best_model_retrained: sklearn model
        most accurate model for your data, retrained using full dataset
    X: pandas.DataFrame
        table of features constructed from data
    y: pandas.DataFrame
        table of labels constructed from data
    """
    # -----Split data into feature columns and labels
    X = data[feature_columns]
    y = data[labels]

    # -----Initialize evaluation metrics
    # NOTE: These metrics are for Regression models. If you are using Classification or Clustering models, use other
    # metrics. See here for more info: https://scikit-learn.org/stable/modules/model_evaluation.html
    mean_abs_err = np.zeros(len(models))
    mean_sq_err = np.zeros(len(models))
    mean_abs_percentage_err = np.zeros(len(models))
    max_err = np.zeros(len(models))
    rsq = np.zeros(len(models))

    # -----Iterate over models
    for i, (name, model) in enumerate(zip(model_names, models)):

        print(name)

        # Conduct K-Fold cross-validation
        kfold = KFold(n_splits=num_folds, shuffle=True, random_state=1)
        mean_abs_err_folds = np.zeros(num_folds)
        mean_sq_err_folds = np.zeros(num_folds)
        mean_abs_percentage_err_folds = np.zeros(num_folds)
        max_err_folds = np.zeros(num_folds)
        rsq_folds = np.zeros(num_folds)

        # loop through fold indices
        j = 0  # fold counter
        for train_ix, test_ix in kfold.split(X):
            # split data into training and testing using kfold indices
            X_train, X_test = X.iloc[train_ix], X.iloc[test_ix]
            y_train, y_test = np.ravel(y.iloc[train_ix].values), np.ravel(y.iloc[test_ix].values)

            # fit model to X_train and y_train
            model.fit(X_train, y_train)

            # predict outputs for X_test values
            y_pred = model.predict(X_test)

            # calculate evaluation metrics
            mean_abs_err_folds[j] = sklearn.metrics.mean_absolute_error(y_test, y_pred)
            mean_sq_err_folds[j] = sklearn.metrics.mean_squared_error(y_test, y_pred)
            mean_abs_percentage_err_folds[j] = sklearn.metrics.mean_absolute_percentage_error(y_test, y_pred)
            max_err_folds[j] = sklearn.metrics.max_error(y_test, y_pred)
            rsq_folds = sklearn.metrics.r2_score(y_test, y_pred)

            j += 1

        # take mean of evaluation metrics for all folds
        mean_abs_err[i] = np.nanmean(mean_abs_err_folds)
        mean_sq_err[i] = np.nanmean(mean_sq_err_folds)
        mean_abs_percentage_err[i] = np.nanmean(rsq_folds)
        max_err[i] = np.nanmean(max_err_folds)
        rsq[i] = np.nanmean(rsq_folds)

        # display performance results
        print('    Mean absolute error = ' + str(mean_abs_err[i]))

    # -----Save performances from all models
    if save_performances:
        performances_df = pd.DataFrame({'Model': model_names,
                                        'Mean absolute error': mean_abs_err,
                                        'Mean squared error': mean_sq_err,
                                        'Mean absolute percentage error': mean_abs_percentage_err,
                                        'Maximum error': max_err,
                                        'R^2': rsq})
        performances_df.to_csv(os.path.join(out_path, performances_fn), index=False)
        print('Evaluation metrics for all models saved to file:', os.path.join(out_path, performances_fn))

    # -----Determine best model
    ibest = np.argwhere(mean_abs_err == np.min(mean_abs_err))[0][0]
    best_model = models[ibest]
    best_model_name = model_names[ibest]
    print('Most accurate classifier: ' + best_model_name)
    print('Mean absolute error = ', np.min(mean_abs_err))

    # -----Retrain best model with full training dataset and save to file
    best_model_retrained = best_model.fit(X, y)
    dump(best_model_retrained, os.path.join(out_path, best_model_fn))
    print('Most accurate model retrained and saved to file: ' + os.path.join(out_path, best_model_fn))

    return best_model_retrained, X, y


def assess_model_feature_importances(model, X, y, feature_columns, feature_columns_display=None, out_path=None,
                                     importances_fn='model_feature_importances.csv', figure_out_path=None,
                                     figure_fn='model_feature_importances.png', n_repeats=100, random_state=42):
    """
    Assess permutation feature importance for your model and input features and labels.
    See here for more information: https://scikit-learn.org/stable/modules/permutation_importance.html

    Parameters
    ----------
    model: sklearn model
        model to assess feature importances
    X: pandas.DataFrame
        table of features
    y: pandas.DataFrame
        table of labels
    feature_columns: str
        list of feature names, used for constructing data table and plotting
    out_path: str
        path in directory where importance information will be saved
    importances_fn: str
        file name for output importances dictionary, saved to out_path
    figure_out_path: str
        path in directory where figure will be saved
    figure_fn: str
        file name for importances box plot figure, saved to figure_out_path
    n_repeats: int
        number of iterations for permutation
    random_state: int
        random state used for shuffling each feature

    Returns
    -------
    feature_importances: dict
        results for permutation feature importance
    """

    # Check input variables
    if not feature_columns_display:
        feature_columns_display = feature_columns

    # Calculate feature importances using permutatiion
    feature_importances = permutation_importance(model, X, y, n_repeats=n_repeats, random_state=random_state, n_jobs=2)
    # convert to pandas.DataFrame
    feature_importances_df = pd.DataFrame()
    for i, column in enumerate(feature_columns):
        feature_importances_df[column] = feature_importances['importances'][i]

    # plot
    plt.rcParams.update({'font.size': 12, 'font.sans-serif': 'Arial'})
    fig, ax = plt.subplots(1, 1, figsize=(6/5 * len(feature_columns), 6))
    feature_importances_df.plot(ax=ax,
                                kind='box',
                                color=dict(boxes='k', whiskers='k', medians='b', caps='k'),
                                boxprops=dict(linestyle='-', linewidth=1.5),
                                flierprops=dict(linestyle='-', linewidth=1.5),
                                medianprops=dict(linestyle='-', linewidth=1.5),
                                whiskerprops=dict(linestyle='-', linewidth=1.5),
                                capprops=dict(linestyle='-', linewidth=1.5),
                                showfliers=True)
    ax.set_xticklabels(feature_columns_display, rotation=90)
    ax.set_ylim(0, np.nanmax(np.ravel(feature_importances['importances'])) * 1.1)
    ax.set_ylabel('Importance')
    ax.grid()
    plt.show()

    # save dataframe to file if out_path is valid
    if os.path.exists(out_path):
        feature_importances_fn = os.path.join(out_path, importances_fn)
        feature_importances_df.to_csv(feature_importances_fn, index=False)
        print('importances data frame saved to file: ' + feature_importances_fn)

        # save figure to file if figure_out_path is valid
        if os.path.exists(figure_out_path):
            fig_fn = os.path.join(figure_out_path, figure_fn)
            fig.savefig(fig_fn, dpi=300, bbox_inches='tight')
            print('figure saved to file: ' + fig_fn)
        else:
            print('Variable figure_out_path not valid path in directory, not saving figure...')
    else:
        print('Variable out_path not valid path in directory, not saving output dataframe...')

    return feature_importances


def reduce_memory_usage(df, verbose=True):
    """
    Reduce memory usage in pandas.DataFrame
    From Bex T (2021): https://towardsdatascience.com/6-pandas-mistakes-that-silently-tell-you-are-a-rookie-b566a252e60d

    Parameters
    ----------
    df: pandas.DataFrame
        input dataframe
    verbose: bool
        whether to output verbage (default=True)

    Returns
    ----------
    df: pandas.DataFrame
        output dataframe with reduced memory usage
    """
    numerics = ["int8", "int16", "int32", "int64", "float16", "float32", "float64"]
    start_mem = df.memory_usage().sum() / 1024 ** 2
    for col in df.columns:
        col_type = df[col].dtypes
        if col_type in numerics:
            c_min = df[col].min()
            c_max = df[col].max()
            if str(col_type)[:3] == "int":
                if c_min > np.iinfo(np.int8).min and c_max < np.iinfo(np.int8).max:
                    df[col] = df[col].astype(np.int8)
                elif c_min > np.iinfo(np.int16).min and c_max < np.iinfo(np.int16).max:
                    df[col] = df[col].astype(np.int16)
                elif c_min > np.iinfo(np.int32).min and c_max < np.iinfo(np.int32).max:
                    df[col] = df[col].astype(np.int32)
                elif c_min > np.iinfo(np.int64).min and c_max < np.iinfo(np.int64).max:
                    df[col] = df[col].astype(np.int64)
            else:
                #                if (
                #                    c_min > np.finfo(np.float16).min
                #                    and c_max < np.finfo(np.float16).max
                #                ):
                #                    df[col] = df[col].astype(np.float16) # float16 not compatible with linalg
                if (  # elif (
                        c_min > np.finfo(np.float32).min
                        and c_max < np.finfo(np.float32).max
                ):
                    df[col] = df[col].astype(np.float32)
                else:
                    df[col] = df[col].astype(np.float64)
    end_mem = df.memory_usage().sum() / 1024 ** 2
    if verbose:
        print(
            "pandas.DataFrame memory usage decreased to {:.2f} Mb ({:.1f}% reduction)".format(
                end_mem, 100 * (start_mem - end_mem) / start_mem
            )
        )
    return df
