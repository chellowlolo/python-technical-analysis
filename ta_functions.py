from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from itertools import izip
from textwrap import dedent

from IPython.core.display import display
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pandas_datareader import data
import seaborn as sns

blue, green, red, purple, yellow, teal = sns.color_palette('colorblind')
black = (0, 0, 0)
white = (1, 1, 1)
blues = sns.color_palette('Blues', n_colors=6)[::-1]


def _listify_security(securities):
    """If input is a string, convert it to a list. If the input is a
    list, keep it the same.
    """

    if isinstance(securities, str):
        return [securities]
    elif isinstance(securities, list)\
            or isinstance(securities, pd.DataFrame)\
            or isinstance(securities, set):
        return securities


def _get_security_names(security_df):
    """Extracts the security names from the merged DataFrame."""
    _col_values = [word.split('_')[-1] for word in security_df.columns]
    return set(_col_values)


def _trim_security_name(sec_string, sec_name):
    """Trims the security name from the end of the string with an
    underscore ahead of it."""

    last_index = sec_string.rfind('_' + sec_name)
    
    # Determines whether sec_name is truly at the end of the string
    # Adds 1 to take into account the '_'
    if last_index + len(sec_name) + 1 == len(sec_string):
        return sec_string[:last_index]
    return sec_string


def generate_bollinger_columns(security_df, securities, col_name,
                               bollinger_std, bollinger_len):
    """Creates columns for Bollinger bands and buy signals.

    Parameters
    ----------
    security_df : DataFrame
        The merged DataFrame of security data
    securities : list
        The corresponding list of securities, ETFs, etc.
    col_name : str
        Close, Open, etc.
    bollinger_std : float
        The standard deviation of the Bollinger bands
    bollinger_len : int
        The number of days to use for the moving average

    Returns
    -------
    A Pandas DataFrame with the new Bollinger columns
    """

    security_df = security_df.copy()

    securities = _listify_security(securities)

    for security in securities:
        col_name = col_name.lower()
        security = security.lower()
        input_col = col_name + '_' + security

        # Set column names for bollinger bands
        bollinger_high = '{}_bollinger_high_{}'.format(col_name, security)
        bollinger_low = '{}_bollinger_low_{}'.format(col_name, security)

        # Get rolling mean and standard deviation
        rolling_window = security_df[input_col].rolling(bollinger_len)
        rolling_mean = rolling_window.mean()
        rolling_std = rolling_window.std()

        # Set bollinger band columns
        security_df[bollinger_high] = rolling_mean + bollinger_std * rolling_std
        security_df[bollinger_low] = rolling_mean - bollinger_std * rolling_std

        buy_signal = security_df[input_col] < security_df[bollinger_low]
        sell_signal = security_df[input_col] > security_df[bollinger_high]

        signal_col_name = 'bollinger_signal_{}'.format(security.lower())
        security_df[signal_col_name] = ['Buy' if buy 
                                        else 'Sell' if sell
                                        else 'N/A'
                                            for buy, sell in zip(buy_signal,
                                                                 sell_signal)]

    return security_df.dropna()


def generate_ma_columns(security_df, securities, col_name, ndays):
    """Create columns for moving averages and determines when there are
    crossovers.

    Parameters
    ----------
    security_df : DataFrame
        The merged DataFrame of security data
    securities : list
        The corresponding list of securities, ETFs, etc.
    col_name : str
        Close, Open, etc.
    ndays : list of int
        A list of the moving average lengths we want to generate

    Returns
    -------
    A Pandas DataFrame with the new MA columns
    """

    security_df = security_df.copy()
    if len(ndays) != 2:
        raise Exception('Length of ndays must be 2.')

    securities = _listify_security(securities)
    
    for security in securities:
        # Add moving average
        col_name = col_name.lower()
        security = security.lower()
        input_col = col_name + '_' + security

        # Create moving average columns
        for n in ndays:
            final_col = '{}_{}d_ma_{}'.format(col_name, n, security)
            security_df[final_col] = security_df[input_col].rolling(n).mean()

        short_ma_col = '{}_{}d_ma_{}'.format(col_name, ndays[0], security)
        long_ma_col = '{}_{}d_ma_{}'.format(col_name, ndays[1], security)
        short_ma = security_df[short_ma_col]
        long_ma = security_df[long_ma_col]

        ma_diff_col_name = 'ma_diff_' + security
        security_df[ma_diff_col_name] = short_ma - long_ma

        crossover = np.array(security_df[ma_diff_col_name])[:-1]\
                    * np.array(security_df[ma_diff_col_name][1:])
        # Account for missing entry
        crossover = [0] + crossover.tolist()

        crossover_col_name = 'crossover_{}'.format(security)
        security_df[crossover_col_name] = np.sign(crossover)
        # Equal to 1 if crossed over from previous day to current day,
        # i.e., the signs of ma_diff switches
        security_df[crossover_col_name] = security_df[crossover_col_name]\
            .map({1:0, 0:0, -1:1})

        # Make a new variable signal_SECURITY which determines, based
        # off the moving average, whether to buy, sell or do nothing. We
        # buy when short_ma is larger than long_ma
        signal_col_name = 'crossover_signal_{}'.format(security)
        security_df[signal_col_name] = (short_ma > long_ma)\
            .map({True: 'Buy', False: 'Sell'})

        # Next, we only do this when a crossover has occurred, so we
        # need to remove pre-existing signals
        security_df.loc[security_df[crossover_col_name] == 0, signal_col_name] = 'N/A'
    
    return security_df.dropna()


def generate_returns(security_df, col_name):
    """Generates the returns of a given security.

    Parameters
    ----------
    security_df : A Pandas DataFrame with the security information.
    col_name : The column name to generate returns for

    Returns
    -------
    sec_returns : A Pandas Series of the returns of the given column
    """

    # Get the first security name
    security_names = _get_security_names(security_df)
    if len(security_names) > 1:
        raise(Exception('There can only be one security in the DataFrame'))
    else:
        security_name = list(security_names)[0]

    col_name = col_name + '_' + security_name
    df_col = security_df[col_name]
    df_last_col = df_col.shift(1)

    sec_returns = ((df_col - df_last_col)/df_last_col)
    return sec_returns

def get_security_data(securities, start_date, end_date=None,
                      data_source='google'):
    """Gets all securities in securities and merges them into a
    DataFrame.

    Parameters
    ----------
    securities : str or list of str
        A string indicating the desired security or a list of strings
        indicating the desired securities
    end_date : str, default None
        A string indicating the end date of our data. If set to None,
        then end_date will be set as date.today()
    data_source : str, default 'google'
        The source of the security data
    """

    securities = _listify_security(securities)

    if end_date is None:
        end_date = date.today()

    try:
        df_list = [data.DataReader(security, data_source=data_source,
                                   start=start_date, end=end_date)
                       for security in securities]
    except:
        columns = ['open', 'high', 'low', 'close', 'volume']
        columns = [s + '_' + security.lower() for s in columns]
        return pd.DataFrame(columns=columns)

    # Append security name to columns
    for security, df in izip(securities, df_list):
        df.columns = ['{}_{}'.format(col, security).lower()
                          for col in df.columns]

    merged_df = df_list[0].copy()
    for i in range(1, len(df_list)):
        merged_df = merged_df.join(df_list[i])

    return merged_df


def run_simulation(securities, col_name, start_date, end_date=None,
                   data_source='google', data_store=None, **simulation_args):
    """Run a trading simulation for a list of securities. This is a
    wrapper around run_simulation_df(). Its purpose is to load the data,
    then run run_simulation_df() on it, so we do not need to load the
    data into a DataFrame ahead of time.

    Parameters
    ----------
    securities : str
        A string representing a single security, a list of securities,
        ETFs, etc., or a DataFrame containing the already merged data.
    col_name : str
        Close, Open, etc.
    start_date : str
        A string indicating the start date of our data
    end_date : str, default None
         A string indicating the end date of our data. If set to None,
         then end_date will be set as date.today()
    start_cash_amt : int, default 10000
        Starting portfolio cash amount
    data_source : str, default 'google'
        The source of the security data
    data_store : data_storage object, default None
         A data_storage object to hold the security data. If not
        specified, then download data each time.
    simulation_args : Remaining keyword arguments
    """

    securities = _listify_security(securities)

    if end_date is None:
        end_date = date.today()

    if data_store is None:
        # Pull security data from online
        security_data = get_security_data(securities, start_date, end_date,
                                          data_source=data_source)

    else:
        # Pull security data from data store. If they don't exist, then
        # take from online
        df_list = []
        for sec in securities:
            if sec.upper() in data_store.data_store_dict:
                _df = data_store.load_security_data(sec,
                                                    start_date,
                                                    end_date,
                                                   )
            else:
                _df = data_store.get_security_data(sec,
                                                   start_date,
                                                   end_date,
                                                   data_source=data_source
                                                  )
            df_list.append(_df)

        security_data = df_list[0].copy()

        for i in range(1, len(df_list)):
            security_data = security_data.join(df_list[i])

    port = run_simulation_df(security_data, col_name, start_cash_amt,
                             **simulation_args)
    return port
   
def run_simulation_df(security_data, col_name, start_cash_amt=10000,
                      indicators=dict(ma_crossovers=[5, 10]), verbose=True,
                      plot_options=set(['transactions'])):
    """Runs a trading simulation on a DataFrame containing all of the
    security data information. This is designed to run on the output
    DataFrame of the get_security_data function.

    Parameters
    ----------
    security_data : DataFrame
        A Pandas DataFrame with the relevant stock data
    col_name : str
        Close, Open, etc.
    start_cash_amt : int, default 10000
        Starting portfolio cash amount
    indicators : dict, default {'ma_crossovers': [5, 10]}
        a dictionary of which indicators to use, where the keys are
        strings representing the indicators and the values indicate the
        parameters associated with the indicators
        
        possible keys: 'ma_crossovers', 'rsi', 'bollinger_std', and
                        'bollinger_len'
    verbose : bool, default True
        A boolean of whether to print each trade (Default: True)
    plot_options : set
        A set of which plotting options. This option can take more than
        one option
        Possible options: 'transactions', 'ma'
    """

    def _get_ma_crossovers_price(index, row, security, purchase_price):
        """Checks for MA crossovers, executes transaction if satisfies
        criteria, and updates purchase_price."""

        close_col_name = 'close_' + security
        ma_diff_col_name = 'ma_diff_' + security

        # If ma_diff is positive on a crossover, then it is trending
        # upwards since 50d ma is smaller than 15d ma
        if security not in bought_securities\
                and row[ma_diff_col_name] > 0\
                and sec_port.get_total_cash_amt() > purchase_price:
            # Buy securities
            sec_port.buy_max_securities(security, 
                                        row[close_col_name], 
                                        index 
                                       )
            bought_securities.add(security)
            purchase_price = row[close_col_name]
        elif security in bought_securities\
                and row[ma_diff_col_name] < 0\
                and row[close_col_name] > purchase_price:
            # Sell securities
            sec_port.sell_all_securities(security, 
                                         row[close_col_name],
                                         index
                                        )
            bought_securities.remove(security)

        return purchase_price

    def _get_bollinger_price(index, row, security, purchase_price):
        """Checks for bollinger criteria, executes transaction if
        passes, and updates purchase_price."""

        close_col_name = 'close_{}'.format(security)
        high_col_name = 'close_{}_bollinger_high'.format(security)
        low_col_name = 'close_{}_bollinger_low'.format(security)

        if security not in bought_securities\
                and row[close_col_name] < row[low_col_name]\
                and sec_port.get_total_cash_amt() > purchase_price:
            # Buy securities
            sec_port.buy_max_securities(security,
                                        row[close_col_name],
                                        index
                                       )
            bought_securities.add(security)
            purchase_price = row[close_col_name]
        elif security in bought_securities\
                and row[close_col_name] > row[high_col_name]:
                # and row[close_col_name] > purchase_price:
            # Sell securities
            sec_port.sell_all_securities(security, 
                                         row[close_col_name],
                                         index
                                        )
            bought_securities.remove(security)

        return purchase_price

    def _run_simulation():
        """Runs through the simulation."""
        purchase_price = 0
        # For each day
        for index, row in security_data.iterrows():
            for security in securities:
                crossover_col_name = 'crossover_' + security
                if 'ma_crossovers' in indicators\
                        and row[crossover_col_name] == 1:
                    purchase_price = _get_ma_crossovers_price(index,
                                                              row,
                                                              security,
                                                              purchase_price
                                                             )

                if 'bollinger_len' in indicators\
                       and 'bollinger_std' in indicators:
                    purchase_price = _get_bollinger_price(index,
                                                          row,
                                                          security,
                                                          purchase_price
                                                         )

    def _plot_simulation():
        """Plot the security and relevant simulation information."""
        for security in securities:
            close_col_name = 'close_' + security
            # If anything should be plotted
            if len(plot_options) > 0:
                # Plot security closing prices
                security_data[close_col_name].plot(c=black)

                if 'ma_crossovers' in indicators and 'ma' in plot_options:
                    ndays = indicators['ma_crossovers']
                    # Plot each moving average crossover
                    for i in xrange(len(ndays)):
                        day = ndays[i]
                        ma_col_name = 'close_{}_{}d_ma'.format(security, day)

                        # Plot moving average columns
                        plt.plot(security_data.index,
                                 security_data[ma_col_name],
                                 c=blues[i]
                                )

                if 'bollinger_std' in indicators\
                        and 'bollinger' in plot_options:
                    # Get bollinger high and low column names
                    high_col_name = 'close_{}_bollinger_high'.format(security)
                    low_col_name = 'close_{}_bollinger_low'.format(security)

                    # Plot bollinger bands
                    plt.plot(security_data.index, security_data[high_col_name],
                             c=black, linestyle='--', alpha=0.5)
                    plt.plot(security_data.index, security_data[low_col_name],
                             c=black, linestyle='--', alpha=0.5)

        if 'transactions' in plot_options:
            for row in sec_port.get_all_transactions().itertuples():
                if row.trans_type == 'Buy':
                    plt.axvline(x=row.date, label='Buy', linewidth=2.5,
                                linestyle='--', c=red)
                elif row.trans_type == 'Sell':
                    plt.axvline(x=row.date, label='Sell', linewidth=2.5,
                                linestyle='--', c=green)

    securities = _get_security_names(security_data)
    col_name = col_name.lower()
    if 'ma_crossovers' in indicators:
        security_data = generate_ma_columns(security_data,
                                            securities,
                                            col_name,
                                            indicators['ma_crossovers']
                                           )
    if 'bollinger_std' in indicators and 'bollinger_len' in indicators:
        security_data = generate_bollinger_columns(security_data,
                                                   securities,
                                                   col_name,
                                                   indicators['bollinger_std'],
                                                   indicators['bollinger_len']
                                                  )

    sec_port = security_portfolio(start_cash_amt, verbose=verbose)
    bought_securities = set()

    _run_simulation()
    _plot_simulation()
    return sec_port


def get_buy_sell_signals(security, col_name, start_date, end_date=None,
                         show_plot=True, data_source='google',
                         indicators={'ma_crossovers': [5, 10]},
                         signals=[], data_store=None, **kwargs):
    """Gets buy and sell signals given indicators and plots them.

    Parameters
    ----------
    security : str
        The ticker symbol
    col_name : str
        Open, Close, etc.
    start_date : str
        A string representing the start date
    end_date : str, default None
        A string indicating the end date of our data. If set to None,
        then end_date will be set as date.today()
    show_plot : bool, default True
        A boolean of whether to plot the security and signals
    data_source : str, default 'google'
        The data source to pull data from
    indicators : dict, default {'ma_crossovers': [5, 10]}
        a dictionary of which indicators to use, where the keys are
        strings representing the indicators and the values indicate the
        parameters associated with the indicators
        
        possible keys: 'ma_crossovers', 'rsi', 'bollinger_std', and
                        'bollinger_len'
    signals : list, default []
        A list of signals to plot. Options: 'buy' and 'sell'.

    Returns
    -------
    signal_df : A DataFrame of the buy and sell signals
    """

    def _plot_security():
        if 'ax' in kwargs:
            ax = kwargs['ax']
            ax.plot(security_df.index, security_df[desired_column], c=black)
        else:
            plt.plot(security_df.index, security_df[desired_column], c=black)
        plt.tight_layout()

    def _plot_bollinger_bands(security_df):
        security_df = generate_bollinger_columns(security_df,
                                                 security,
                                                 col_name,
                                                 bollinger_len=bollinger_len,
                                                 bollinger_std=bollinger_std
                                                )

        # Plot the upper and lower bollinger bands
        if show_plot:
            if 'ax' in kwargs:
                ax = kwargs['ax']
                ax.plot(security_df.index, security_df[bollinger_high_col],
                        c=black, linestyle='--', alpha=0.5)
                ax.plot(security_df.index, security_df[bollinger_low_col],
                        c=black, linestyle='--', alpha=0.5)
            else:
                plt.plot(security_df.index, security_df[bollinger_high_col],
                         c=black, linestyle='--', alpha=0.5)
                plt.plot(security_df.index, security_df[bollinger_low_col],
                         c=black, linestyle='--', alpha=0.5)

        return security_df

    def _plot_ma_crossovers(security_df):
        ndays = indicators['ma_crossovers']
        security_df = generate_ma_columns(security_df, security, col_name,
                                          ndays=ndays)

        if show_plot:
            for colour, nday in izip(blues, ndays):
                ma_crossover_col = '{}_{}d_ma_{}'.format(col_name,
                                                         nday,
                                                         security
                                                        )
                if 'ax' in kwargs:
                    ax = kwargs['ax']
                    ax.plot(security_df.index, security_df[ma_crossover_col],
                            c=colour, alpha=0.5)
                else:
                    plt.plot(security_df.index, security_df[ma_crossover_col],
                             c=colour, alpha=0.5)

        return security_df

    def _plot_signals(df, type_, colour):
        """Plots buy or sell signals.

        Parameters
        ----------
        df : DataFrame
            buy_df or sell_df
        type_ : str
            'Sell' or 'Buy'
        colour : Plotting colour
        """

        for row in df.itertuples():
            if 'ax' in kwargs:
                ax = kwargs['ax']
                ax.axvline(x=row.Index, label=type_, c=colour,
                           linestyle='--', linewidth=2.5)
            else:
                plt.axvline(x=row.Index, label=type_, c=colour,
                            linestyle='--', linewidth=2.5)

    def _get_security_df(security, start_date, end_date, data_store):
        if data_store is None:
            # If no data store is specified, use get_security_data
            return get_security_data(security.upper(),
                                     start_date,
                                     end_date,
                                     data_source=data_source
                                    )
        elif security.upper() not in data_store.data_store_dict:
            # If a data store is specified, use that to get security data
            return data_store.get_security_data(security.upper(),
                                                start_date,
                                                end_date,
                                                data_source=data_source
                                               )
        else:
            # If the security is in the data store, load it from there
            return data_store.load_security_data(security.upper(),
                                                 start_date,
                                                 end_date
                                                )

    if end_date is None:
        end_date = date.today()

    security = security.lower()
    col_name = col_name.lower()
    desired_column = col_name + '_' + security
    bollinger_high_col = '{}_bollinger_high_{}'.format(col_name, security)
    bollinger_low_col = '{}_bollinger_low_{}'.format(col_name, security)

    security_df = _get_security_df(security, start_date, end_date, data_store)

    if show_plot:
        _plot_security()

    if 'bollinger_len' in indicators and 'bollinger_std' in indicators:
        bollinger_len = indicators['bollinger_len']
        bollinger_std = indicators['bollinger_std']
        security_df = _plot_bollinger_bands(security_df)

    if 'ma_crossovers' in indicators:
        ndays = indicators['ma_crossovers']
        security_df = _plot_ma_crossovers(security_df)

    signal_df = pd.DataFrame()
    # Plot buy signals
    # TODO: Clean up this part
    if 'buy' in signals and security_df.shape[0] > 0:
        if 'ma_crossovers' in indicators:
            buy_col = 'crossover_signal_{}'.format(security)
            buy_df = security_df[security_df[buy_col] == 'Buy'].copy()
            signal_df = pd.concat([signal_df, buy_df])

            if show_plot:
                _plot_signals(buy_df, 'Buy', red)

        if 'bollinger_len' in indicators and 'bollinger_std' in indicators:
            buy_col = 'bollinger_signal_{}'.format(security)
            buy_df = security_df[security_df[buy_col] == 'Buy'].copy()
            signal_df = pd.concat([signal_df, buy_df])

            if show_plot:
                _plot_signals(buy_df, 'Buy', red)

    # Plot sell signals
    if 'sell' in signals and security_df.shape[0] > 0:
        if 'ma_crossovers' in indicators:
            sell_col = 'crossover_signal_{}'.format(security)
            sell_df = security_df[security_df[sell_col] == 'Sell'].copy()
            signal_df = pd.concat([signal_df, sell_df])

            if show_plot:
                _plot_signals(sell_df, 'Sell', green)

        if 'bollinger_len' in indicators and 'bollinger_std' in indicators:
            sell_col = 'bollinger_signal_{}'.format(security)
            sell_df = security_df[security_df[sell_col] == 'Sell'].copy()
            signal_df = pd.concat([signal_df, sell_df])

            if show_plot:
                _plot_signals(sell_df, 'Sell', green)

    if signal_df.shape[0] > 0:
        # Remove ticker symbols from column names
        signal_df.columns = [_trim_security_name(s, security)
                                 for s in signal_df.columns]
        # Insert column for ticker symbols
        signal_df.insert(0, 'security', security.upper())
        return signal_df.sort_index().drop_duplicates()
    else:
        return None


def plot_trades(sec_port):
    """Plots the trades."""

    trans_df = sec_port.get_all_transactions()
    for row in trans_df.itertuples():
        if row.trans_type == 'Buy':
            plt.axvline(row.date, linestyle='--', linewidth=3, color=red)
        elif row.trans_type == 'Sell':
            plt.axvline(row.date, linestyle='--', linewidth=3, color=green)


def plot_rsi(security, col_name, start_date, end_date=None, ndays=14,
             thresholds=[20, 80], **kwargs):
    """Plots a single security.

    Parameters
    ----------
    security : str
        The ticker symbol
    col_name : str
        Open, Close, etc.
    start_date : str
        A string representing the start date
    end_date : str, default None
        A string indicating the end date of our data. If set to None,
         then end_date will be set as date.today()
    ndays : int, default 14
        The number of days to use as a lookback period
    thresholds : list of int, default [20, 80]
        The RSI thresholds (Default: [20, 80])
    """

    def _rsi_agg(security_array):
        """Returns RSI."""
        # Get differences of the security
        sec_diff = np.diff(security_array)
        pos_array = sec_diff[sec_diff > 0]    
        neg_array = sec_diff[sec_diff < 0]    
        
        if len(pos_array) > 0:
            pos_mean = pos_array.mean()
        if len(neg_array) > 0:
            neg_mean = -neg_array.mean()
        
        if len(neg_array) == 0 and len(pos_array) == 0:
            rs = 50
        elif len(neg_array) == 0 and len(pos_array) > 0:
            rsi = 100
        elif len(pos_array) == 0 and len(neg_array) > 0:
            rsi = 0
        else:
            rsi = 100 - 100/(1 + float(pos_mean)/float(neg_mean))
        return rsi

    if end_date is None:
        end_date = date.today()

    security = security.lower()
    col_name = col_name.lower()
    desired_column = col_name + '_' + security
    security_df = get_security_data(security, start_date, end_date)
    security_df['rsi'] = security_df[desired_column]\
        .rolling(ndays)\
        .aggregate(_rsi_agg)

    if 'ax' in kwargs:
        ax = kwargs['ax']
        ax.plot(security_df.index, security_df.rsi)
        ax.axhline(y=thresholds[0], linestyle='--', c=black, alpha=0.5)
        ax.axhline(y=thresholds[1], linestyle='--', c=black, alpha=0.5)
        ax.set_ylim(0, 100)
    else:
        plt.plot(security_df.index, security_df.rsi)
        plt.axhline(y=thresholds[0], linestyle='--', c=black, alpha=0.5)
        plt.axhline(y=thresholds[1], linestyle='--', c=black, alpha=0.5)
        plt.ylim(0, 100)

class data_storage:
    def __init__(self):
        self.data_store_dict = {}

    def get_security_data(self, security, start_date, end_date=None,
                          data_source='google', return_df=True):
        """Obtains security data and stores it into dictionary."""
        if end_date is None:
            end_date = date.today()
        
        security_df = get_security_data(security, start_date, end_date,
                                        data_source)
        self.data_store_dict[security] = security_df
        if return_df: 
            return security_df

    def load_security_data(self, security, start_date=None, end_date=None):
        """Loads the security data if it is in the dictionary."""
        if security not in self.data_store_dict:
            raise KeyError('security not in data dictionary.')
        security_df = self.data_store_dict[security].copy()

        if start_date is None and end_date is None: 
            return security_df
        elif start_date is None and end_date is not None:
            return security_df.query('index <= @end_date')
        elif start_date is not None and end_date is None:
            return security_df.query('index >= @start_date')
        else:
            return security_df.query('index >= @start_date & index <= @end_date')

class security_portfolio:
    def __init__(self, total_cash_amt, verbose=False):
        self.start_cash_amt = total_cash_amt
        self.total_cash_amt = total_cash_amt
        self.security_dict = {}
        self.verbose = verbose
        self.trans_df = pd.DataFrame(columns=['date', 'security', 'trans_type',
                                              'security_price', 'amt',
                                              'total_cash_amt'])
            
    def buy_max_securities(self, ticker_symbol, security_price, trans_date):
        """Buy as many securities as possible with current cash."""
        amount = int(np.floor(self.total_cash_amt/security_price))
        self.buy_securities(ticker_symbol, amount, security_price, trans_date)

    def buy_securities(self, ticker_symbol, amount, security_price, trans_date):
        # Check if there is enough cash to buy the securities
        if amount * security_price <= self.total_cash_amt:
            if ticker_symbol in self.security_dict:
                # Increase number of securities
                self.security_dict[ticker_symbol] += amount
            else:
                self.security_dict[ticker_symbol] = amount
                
            # Decrease total cash amount
            start_cash_amt = self.total_cash_amt
            self.total_cash_amt -= amount * security_price
            added_row = [trans_date, ticker_symbol, 'Buy', security_price,
                         security_price * amount, self.total_cash_amt]
            self.trans_df.loc[self.trans_df.shape[0]] = added_row
            
            if self.verbose:
                print 'Bought {} shares of {} at {}.\n\tStart cash: {}.\n\tRemaining cash: {}.\n\tDate: {}'\
                      .format(amount, ticker_symbol, security_price,
                              start_cash_amt, self.total_cash_amt, trans_date)
        else:
            raise Exception('You do not own enough cash to purchase this many securities.')
        
    def get_total_cash_amt(self):
        """Shows the total cash amount."""
        return self.total_cash_amt
            
    def sell_securities(self, ticker_symbol, amount, security_price, trans_date):
        if ticker_symbol in self.security_dict:
            num_of_security = self.security_dict[ticker_symbol]
            if amount > num_of_security:
                raise Exception('You do not have {} shares in this security. Specify lower amount, less than {}.'\
                                .format(amount, num_of_security))
            else:
                # Decrease number of securities
                self.security_dict[ticker_symbol] -= amount
                start_cash_amt = self.total_cash_amt
                # Increase total cash amount
                self.total_cash_amt += amount * security_price
                added_row = [trans_date, ticker_symbol, 'Sell', security_price,
                             security_price * amount, self.total_cash_amt]
                self.trans_df.loc[self.trans_df.shape[0]] = added_row
                if self.verbose:
                    print 'Sold {} shares of {} at {}.\n\tStart cash: {}.\n\tRemaining cash: {}.\n\tDate: {}'\
                          .format(amount, ticker_symbol, security_price, start_cash_amt, self.total_cash_amt, trans_date)
        else:
            raise Exception('You do not own shares in this security.')
            
    def sell_all_securities(self, ticker_symbol, security_price, trans_date):
        """Sell all of a given security."""
        if ticker_symbol in self.security_dict:
            amount = self.security_dict[ticker_symbol]
            self.sell_securities(ticker_symbol, amount, security_price,
                                 trans_date)
        else:
            raise Exception('You do not own shares in this security.')
            
    def show_portfolio(self):
        print 'Total Cash Amount: {}'.format(self.total_cash_amt)
        return self.security_dict
        
    def get_all_transactions(self):
        """Returns a Pandas DataFrame of all transactions."""
        return self.trans_df

    def get_avg_transaction_freq(self):
        """Returns the average transaction frequency."""
        return self.trans_df.date.diff().mean()

    def get_last_sell_cash_amt(self):
        """Get the total cash amt at the last sale. This is an indicator of
        the final cash value of the portfolio.
        """
        df = self.get_all_transactions()
        if 'Sell' in set(df.trans_type):
            return float(df[df.trans_type == 'Sell'].tail(1)['total_cash_amt'])
        else:
            # If there are no sales, return the starting cash amount
            return self.start_cash_amt

    def get_portfolio_value(self, verbose=False):
        """TODO: accomodate for middle of day, if there is no closing
        price yet. 

        Gets the total portfolio value, which is calculated by taking
        all current cash plus the value of all securities owned as of
        today's date.
        """

        def _get_last_close_values():
            """Returns the last closing values of each security in the 
            portfolio.
            """
            last_close_values = {}
            for sec in self.security_dict:
                # Gets last week worth of security data. We need to do this if
                # it's a weekend or a holiday and today's date will not return
                # anything.
                last_wk = get_security_data(sec,
                                            start_date=date.today()
                                                - relativedelta(days=7),
                                            end_date=date.today() 
                                           )
                # Gets the last close price.
                last_close_values[sec] = float(last_wk.ix[-1,
                                               'close_' + sec.lower()])
            return last_close_values

        last_close_values = _get_last_close_values()
        tot_port_value = self.get_total_cash_amt()
        for sec in self.security_dict:
            tot_port_value += self.security_dict[sec] * last_close_values[sec]

        if verbose:
            print self.get_total_cash_amt()
            print self.security_dict
            print last_close_values

        return tot_port_value

    def simulate_ma_crossover(self, securities, verbose=True):
        pass


def pairs_trade(df_1, df_2, column, suffixes, start_date,
                end_date=date.today(), threshold=2, cash_amt=10000):
    """Run pairs trading model.
    
    Parameters
    ----------
    df_1 : DataFrame
        The first DataFrame of security information
    df_2 : DataFrame
        The second DataFrame of security information
    column : str
        The column to look at
    suffixes : list of str
        The suffixes appended to the columns
    start_date : str
        Date indicating when to start trading
    end_date : str
        Date indicating when to stop trading
    threshold : int, default 2
        The threshold to surpass to trade
    cash_amt : int, default 10000
        Starting cash amount
    """

    def _get_column_names(column, suffixes):
        """Retrieves desired column name."""
        return [column + suf for suf in suffixes]

    holding = False
    join_df = pd.merge(df_1, df_2, on='date', suffixes=suffixes)

    column_names = _get_column_names(column, suffixes)

    for i in range(200, len(join_df)):
        rolling_means = [np.mean(join_df[col][i-200 : i]) for col in column_names]
        rolling_stds = [np.std(join_df[col][i-200 : i]) for col in column_names]
        norm_values = [(join_df[column_names[j]][i] - rolling_means[j])/rolling_stds[j] for j in range(2)]

    return join_df
