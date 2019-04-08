/**
 * @license
 * Copyright 2018 Streamlit Inc. All rights reserved.
 *
 * @fileoverview Implements a dialog that is used to configure user settings.
 */

import * as React from 'react';
import {ChangeEvent, PureComponent, ReactNode} from 'react';
import {Button, Modal, ModalBody, ModalFooter, ModalHeader} from 'reactstrap';
import {UserSettings} from './UserSettings';

export interface Props {
  isOpen: boolean;
  isProxyConnected: boolean;
  onClose: () => void;
  onSave: (settings: UserSettings) => void;
  settings: UserSettings;
}

class SettingsDialog extends PureComponent<Props, UserSettings> {
  private _settings: UserSettings;

  public constructor(props: Props) {
    super(props);

    // Holds the settings that will be saved when the "save" button is clicked.
    this.state = {...this.props.settings};

    // Holds the actual settings that Streamlit is using.
    this._settings = {...this.props.settings};
  }

  public render = (): ReactNode => {
    return (
      <Modal
        isOpen={this.props.isOpen}
        toggle={this.handleCancelButtonClick}
        onOpened={this.handleDialogOpen}
      >
        <ModalHeader toggle={this.handleCancelButtonClick}>Settings</ModalHeader>

        <ModalBody>
          <label>
            <input
              disabled={!this.props.isProxyConnected}
              type="checkbox"
              name="runOnSave"
              checked={this.state.runOnSave && this.props.isProxyConnected}
              onChange={this.handleCheckboxChange}
            />
            {' '}
            Run on save
          </label>
          <br/>
          <label>
            <input
              type="checkbox"
              name="wideMode"
              checked={this.state.wideMode}
              onChange={this.handleCheckboxChange}
            />
            {' '}
            Show report in wide mode
          </label>
        </ModalBody>

        <ModalFooter>
          <Button
            color="secondary"
            onClick={this.handleCancelButtonClick}>
            Cancel
          </Button>
          <Button
            color="primary"
            onClick={this.handleSaveButtonClick}>
            Save
          </Button>
        </ModalFooter>
      </Modal>
    );
  };

  private handleDialogOpen = () => {
    this.setState({...this._settings});
  };

  private changeSingleSetting = (name: string, value: boolean) => {
    // TypeScript doesn't currently have a good solution for setState with
    // a dynamic key name:
    // https://github.com/DefinitelyTyped/DefinitelyTyped/issues/26635
    this.setState(state => ({...state, [name]: value}));
  };

  private handleCheckboxChange = (e: ChangeEvent<HTMLInputElement>) => {
    this.changeSingleSetting(e.target.name, e.target.checked);
  };

  private handleCancelButtonClick = () => {
    // Discard settings from this.state by not saving them in this.settings.
    // this.settings = {...this.state};
    this.props.onClose();
  };

  private handleSaveButtonClick = () => {
    this._settings = {...this.state};
    this.props.onSave(this._settings);
    this.props.onClose();
  };
}

export default SettingsDialog;
