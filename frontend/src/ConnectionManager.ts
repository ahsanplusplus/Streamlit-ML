/**
 * @license
 * Copyright 2018 Streamlit Inc. All rights reserved.
 *
 * @fileoverview Manages our connection to the Proxy.
 */

import url from 'url';

import StaticConnection from './StaticConnection';
import WebsocketConnection from './WebsocketConnection';
import {ConnectionState} from './ConnectionState';
import {IS_DEV_ENV, WEBSOCKET_PORT_DEV} from './baseconsts';
import {configureCredentials, getObject} from './s3helper';
import {logError} from './log';

interface Props {
  /**
   * Function that shows the user a login box and returns a promise which
   * gets resolved when the user goes through the login flow.
   */
  getUserLogin: () => Promise<string>;

  /**
   * Function to be called when we receive a message from the proxy.
   */
  onMessage: (message: any) => void;

  /**
   * Function to be called when the connection errors out.
   */
  onConnectionError: (errorMessage: string) => void;

  /**
   * Function that should be called to set the current report's name in the
   * parent component.
   */
  setReportName: (reportName: string) => void;

  /**
   * Called when our ConnectionState is changed.
   */
  connectionStateChanged: (connectionState: ConnectionState) => void;
}

/**
 * Params for our setConnectionState function
 */
interface SetConnectionStateParams {
  connectionState: ConnectionState;
  errMsg?: string;
}

export class ConnectionManager {
  private readonly props: Props;
  private connection?: WebsocketConnection | StaticConnection;
  private connectionState: ConnectionState = ConnectionState.INITIAL;

  public constructor(props: Props) {
    this.props = props;

    // This method returns a promise, but we don't care about its result.
    this.connect();
  }

  /**
   * Indicates whether we're connected to the proxy.
   */
  public isConnected(): boolean {
    return this.connectionState === ConnectionState.CONNECTED;
  }

  public isStaticConnection(): boolean {
    return this.connectionState === ConnectionState.STATIC;
  }

  public sendMessage(obj: any): void {
    if (this.connection instanceof WebsocketConnection &&
      this.isConnected()) {
      this.connection.sendMessage(obj);
    } else {
      // Don't need to make a big deal out of this. Just print to console.
      logError(`Cannot send message when proxy is disconnected: ${obj}`);
    }
  }

  private async connect(): Promise<void> {
    const {query} = url.parse(window.location.href, true);
    const reportName = query.name as string;
    const reportId = query.id as string;

    try {
      if (reportName !== undefined) {
        this.props.setReportName(reportName);
        this.connection = await this.connectBasedOnWindowUrl(reportName);

      } else if (reportId !== undefined) {
        this.connection = await this.connectBasedOnManifest(reportId);

      } else {
        throw new Error('URL must contain either a report name or an ID.');
      }
    } catch (err) {
      this.setConnectionState({
        connectionState: ConnectionState.ERROR,
        errMsg: err.message,
      });
    }
  }

  private setConnectionState = ({connectionState, errMsg}: SetConnectionStateParams): void => {
    if (this.connectionState !== connectionState) {
      this.connectionState = connectionState;
      this.props.connectionStateChanged(connectionState);
    }

    if (connectionState === ConnectionState.ERROR) {
      this.props.onConnectionError(errMsg || 'unknown');
    }
  };

  private connectBasedOnWindowUrl(reportName: string): WebsocketConnection {
    // If dev, always connect to 8501, since window.location.port is the Node
    // server's port 3000.
    // If changed, also change config.py
    const port = IS_DEV_ENV ? WEBSOCKET_PORT_DEV : +window.location.port;
    const uri = getWsUrl(window.location.hostname, port, reportName);

    return new WebsocketConnection({
      uriList: [
        //getWsUrl('1.1.1.1', '9999', 'bad'),  // Uncomment to test timeout.
        //getWsUrl('1.1.1.1', '9999', 'bad2'),  // Uncomment to test timeout.
        uri,
      ],
      onMessage: this.props.onMessage,
      setConnectionState: this.setConnectionState,
    });
  }

  /**
   * Opens either a static connection or a websocket connection, based on what
   * the manifest says.
   */
  private async connectBasedOnManifest(reportId: string): Promise<WebsocketConnection | StaticConnection> {
    const manifest = await this.fetchManifestWithPossibleLogin(reportId);

    return manifest.proxyStatus === 'running' ?
      this.connectToRunningProxyFromManifest(manifest) :
      this.connectToStaticReportFromManifest(reportId, manifest);
  }

  private connectToRunningProxyFromManifest(manifest: any): WebsocketConnection {
    const {
      name, configuredProxyAddress, internalProxyIP, externalProxyIP,
      proxyPort,
    } = manifest;

    const uriList = configuredProxyAddress ?
      [getWsUrl(configuredProxyAddress, proxyPort, name)] :
      [
        getWsUrl(externalProxyIP, proxyPort, name),
        getWsUrl(internalProxyIP, proxyPort, name),
      ];

    return new WebsocketConnection({
      uriList,
      onMessage: this.props.onMessage,
      setConnectionState: this.setConnectionState,
    });
  }

  private connectToStaticReportFromManifest(reportId: string, manifest: any): StaticConnection {
    return new StaticConnection({
      manifest,
      reportId,
      onMessage: this.props.onMessage,
      setConnectionState: this.setConnectionState,
      setReportName: this.props.setReportName,
    });
  }

  private async fetchManifestWithPossibleLogin(reportId: string): Promise<any> {
    let manifest;
    let permissionError = false;

    try {
      manifest = await fetchManifest(reportId);
    } catch (err) {
      if (err.message === 'PermissionError') {
        permissionError = true;
      } else {
        logError(err);
        throw new Error('Unable to fetch report.');
      }
    }

    if (permissionError) {
      const idToken = await this.props.getUserLogin();
      try {
        await configureCredentials(idToken);
        manifest = await fetchManifest(reportId);
      } catch (err) {
        logError(err);
        throw new Error('Unable to log in.');
      }
    }

    if (!manifest) {
      throw new Error('Unknown error fetching report.');
    }

    return manifest;
  }
}

async function fetchManifest(reportId: string): Promise<any> {
  const {hostname, pathname} = url.parse(window.location.href, true);
  if (pathname == null) {
    throw new Error(`No pathname in URL ${window.location.href}`);
  }

  // IMPORTANT: The bucket name must match the host name!
  const bucket = hostname;
  const version = pathname.split('/')[1];
  const manifestKey = `${version}/reports/${reportId}/manifest.json`;
  const data = await getObject({Bucket: bucket, Key: manifestKey});
  return data.json();
}

function getWsUrl(host: string, port: number, reportName: string): string {
  return `ws://${host}:${port}/stream/${encodeURIComponent(reportName)}`;
}
